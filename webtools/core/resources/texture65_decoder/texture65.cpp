// Copyright (c) 2026 Elichika contributors. MIT licensed.
// Isolated, bounded UnityCrunch ETC2_RGBA8Crunched (TextureFormat 65) decoder.
// Upstream decoder files are unchanged; see source-manifest.json and licenses.
#include <algorithm>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <vector>
#include <fcntl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#include "unitycrunch/crn_decomp.h"
#include "etc.h"

namespace {
constexpr size_t MiB = 1024 * 1024;
constexpr size_t MaxInput = 128 * MiB;
constexpr size_t MaxMemory = 256 * MiB;
constexpr size_t MaxCrunchMemory = 64 * MiB;
constexpr uint64_t AllocationMagic = UINT64_C(0x454c494348494b41);
struct Failure : std::runtime_error {
    int code;
    Failure(int value, const char* message) : std::runtime_error(message), code(value) {}
};
struct Budget { size_t used = 0, limit = 0; };
struct alignas(std::max_align_t) Allocation { size_t size; uint64_t magic; };

void* allocate(void* pointer, size_t size, size_t* actual, bool movable, void* context) {
    auto& budget = *static_cast<Budget*>(context);
    Allocation* old = pointer ? static_cast<Allocation*>(pointer) - 1 : nullptr;
    if (old && old->magic != AllocationMagic) std::abort();
    size_t before = old ? old->size : 0;
    if (actual) *actual = before;
    if (!size) {
        if (old) { budget.used -= before; old->magic = 0; std::free(old); }
        if (actual) *actual = 0;
        return nullptr;
    }
    if (old && !movable) return size <= before ? pointer : nullptr;
    if (size > budget.limit || budget.used - before > budget.limit - size) return nullptr;
    auto* result = static_cast<Allocation*>(std::realloc(old, sizeof(Allocation) + size));
    if (!result) return nullptr;
    budget.used = budget.used - before + size;
    result->size = size; result->magic = AllocationMagic;
    if (actual) *actual = size;
    return result + 1;
}
size_t allocation_size(void* pointer, void*) {
    if (!pointer) return 0;
    auto* block = static_cast<Allocation*>(pointer) - 1;
    if (block->magic != AllocationMagic) std::abort();
    return block->size;
}
unsigned dimension(const char* text) {
    if (!text || !*text) throw Failure(3, "Invalid texture dimensions");
    unsigned value = 0;
    for (const char* at = text; *at; ++at) {
        if (*at < '0' || *at > '9' || value > 8192) throw Failure(3, "Invalid texture dimensions");
        value = value * 10 + static_cast<unsigned>(*at - '0');
    }
    if (!value || value > 8192) throw Failure(3, "Texture dimensions exceed the limit");
    return value;
}
void span(size_t offset, size_t size, size_t header, size_t total) {
    if (offset > total || size > total - offset || (size && offset < header))
        throw Failure(7, "Invalid Crunch data offsets");
}
void constrain(int resource, rlim_t maximum) {
    rlimit existing;
    if (getrlimit(resource, &existing)) throw Failure(15, "Cannot read decoder resource limit");
    rlimit limit{std::min(existing.rlim_cur, maximum), std::min(existing.rlim_max, maximum)};
    if (setrlimit(resource, &limit)) throw Failure(15, "Cannot set decoder resource limit");
}
void write_all(int file, const uint8_t* bytes, size_t size) {
    while (size) {
        ssize_t count = write(file, bytes, size);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) throw Failure(13, "Cannot write decoded pixels");
        bytes += count; size -= static_cast<size_t>(count);
    }
}
struct Context {
    unitycrnd::crnd_unpack_context value;
    ~Context() { if (value) unitycrnd::crnd_unpack_end(value); }
};
struct Output {
    int value;
    ~Output() { if (value >= 0) close(value); }
};
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && !std::strcmp(argv[1], "--version")) {
            std::puts("elichika-texture65 1 (UnityCrunch ETC2A RGBA8)"); return 0;
        }
        if (argc != 5 && argc != 7) throw Failure(2, "Usage: texture65 WIDTH HEIGHT INPUT_CRN OUTPUT_RGBA [--mip N]");
        const unsigned width = dimension(argv[1]), height = dimension(argv[2]);
        unsigned mip = 0;
        if (argc == 7) {
            if (std::strcmp(argv[5], "--mip")) throw Failure(2, "Unsupported texture decode option");
            if (!std::strcmp(argv[6], "0")) mip = 0;
            else mip = dimension(argv[6]);
            if (mip > 13) throw Failure(3, "Mip level exceeds the limit");
        }
        if (static_cast<size_t>(width) * height > 4096 * 4096) throw Failure(3, "Texture pixels exceed the limit");
        const unsigned selected_width = std::max(1U, width >> mip), selected_height = std::max(1U, height >> mip);
        const size_t pixels = static_cast<size_t>(selected_width) * selected_height;
        const size_t output_bytes = pixels * 4;
        constrain(RLIMIT_CORE, 0);
        constrain(RLIMIT_CPU, 10);
        constrain(RLIMIT_FSIZE, output_bytes);
        std::ifstream source(argv[3], std::ios::binary | std::ios::ate);
        if (!source) throw Failure(4, "Cannot read encoded texture");
        const auto source_size = source.tellg();
        if (source_size < static_cast<std::streamoff>(sizeof(unitycrnd::crn_header)) || source_size > static_cast<std::streamoff>(MaxInput))
            throw Failure(5, "Encoded texture size is invalid");
        std::vector<uint8_t> encoded(static_cast<size_t>(source_size));
        source.seekg(0); source.read(reinterpret_cast<char*>(encoded.data()), encoded.size());
        if (!source || source.peek() != std::char_traits<char>::eof()) throw Failure(6, "Encoded texture changed or is truncated");
        const auto* header = reinterpret_cast<const unitycrnd::crn_header*>(encoded.data());
        const unsigned levels = header->m_levels;
        unsigned max_levels = 1;
        for (unsigned edge = std::max(width, height); edge > 1; edge >>= 1) ++max_levels;
        const size_t header_bytes = header->m_header_size;
        if (header->m_sig != unitycrnd::crn_header::cCRNSigValue || !levels || levels > max_levels || mip >= levels ||
            header_bytes != offsetof(unitycrnd::crn_header, m_level_ofs) + 4 * levels || header_bytes > encoded.size() ||
            header->m_data_size != encoded.size() || header->m_width != width || header->m_height != height ||
            header->m_faces != 1 || header->m_flags != 0 || header->m_format != cCRNFmtETC2A)
            throw Failure(7, "Unsupported or inconsistent UnityCrunch ETC2A header");
        for (const auto* palette : {&header->m_color_endpoints, &header->m_color_selectors,
                                    &header->m_alpha_endpoints, &header->m_alpha_selectors})
            span(palette->m_ofs, palette->m_size, header_bytes, encoded.size());
        span(header->m_tables_ofs, header->m_tables_size, header_bytes, encoded.size());
        size_t previous = header_bytes;
        const uint8_t* offsets = encoded.data() + offsetof(unitycrnd::crn_header, m_level_ofs);
        for (unsigned level = 0; level < levels; ++level) {
            const uint8_t* at = offsets + 4 * level;
            const size_t offset = (size_t(at[0]) << 24) | (size_t(at[1]) << 16) | (size_t(at[2]) << 8) | at[3];
            if (offset < previous || offset >= encoded.size()) throw Failure(7, "Invalid Crunch mip offsets");
            previous = offset;
        }
        unitycrnd::crn_file_info file;
        if (!unitycrnd::crnd_validate_file(encoded.data(), encoded.size(), &file)) throw Failure(8, "Crunch checksum validation failed");
        unitycrnd::crn_texture_info info;
        if (!unitycrnd::crnd_get_texture_info(encoded.data(), encoded.size(), &info) || info.m_bytes_per_block != 16)
            throw Failure(9, "Invalid ETC2A block layout");
        const size_t pitch = ((size_t(selected_width) + 3) / 4) * 16;
        const size_t block_bytes = pitch * ((size_t(selected_height) + 3) / 4);
        const size_t fixed_bytes = encoded.size() + block_bytes + output_bytes + size_t(selected_width) * 4;
        if (fixed_bytes >= MaxMemory) throw Failure(5, "Texture exceeds the decoder memory budget");
        Budget budget{0, std::min(MaxCrunchMemory, MaxMemory - fixed_bytes)};
        unitycrnd::crnd_set_memory_callbacks(allocate, allocation_size, &budget);
        std::vector<uint8_t> blocks(block_bytes);
        std::vector<uint32_t> bgra(pixels);
        Context context{unitycrnd::crnd_unpack_begin(encoded.data(), encoded.size())};
        if (!context.value) throw Failure(10, "Cannot initialize bounded Crunch decoder");
        void* destination = blocks.data();
        if (!unitycrnd::crnd_unpack_level(context.value, &destination, block_bytes, pitch, mip)) throw Failure(11, "Crunch level decode failed");
        if (!decode_etc2a8(blocks.data(), selected_width, selected_height, bgra.data())) throw Failure(12, "ETC2A pixel decode failed");
        Output output{open(argv[4], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600)};
        if (output.value < 0) throw Failure(13, "Cannot create exclusive decoded output");
        // The upstream decoder returns BGRA bytes on both endian layouts.
        // Preserve straight alpha and encoded color values; do not premultiply
        // or apply color-space conversion. The caller applies Unity's flip.
        const uint8_t* bytes = reinterpret_cast<const uint8_t*>(bgra.data());
        std::vector<uint8_t> row(size_t(selected_width) * 4);
        for (unsigned y = 0; y < selected_height; ++y) {
            const size_t base = size_t(y) * selected_width * 4;
            for (unsigned x = 0; x < selected_width; ++x) {
                const size_t at = size_t(x) * 4;
                row[at] = bytes[base + at + 2]; row[at + 1] = bytes[base + at + 1];
                row[at + 2] = bytes[base + at]; row[at + 3] = bytes[base + at + 3];
            }
            write_all(output.value, row.data(), row.size());
        }
        return 0;
    } catch (const Failure& error) {
        std::fprintf(stderr, "%s\n", error.what()); return error.code;
    } catch (const std::exception&) {
        std::fputs("Texture decoder allocation or I/O failed\n", stderr); return 14;
    }
}
