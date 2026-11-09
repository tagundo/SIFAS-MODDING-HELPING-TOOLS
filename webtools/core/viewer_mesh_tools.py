"""Source-bound UV deletion and explicit vertex/skin editing for the 3D viewer.

Deletion rewrites triangle indices rather than renumbering vertices: skin, morph
and other vertex channels retain their original identities. Every save starts
from the immutable selected originals and writes a new bundle or costume ZIP.
"""
import base64
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import secrets
import shutil
import struct
import tempfile
import time
import zipfile

from . import model_edits

MAX_MESH_VERTICES = 60000
MAX_TRIANGLES = 200000
MAX_CHANGES = 60000
MAX_REQUEST_BYTES = 12 * 1024 * 1024


class MeshToolError(ValueError):
    pass


def _fail(message):
    raise MeshToolError(message)


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value < maximum:
        _fail('Invalid ' + label + '.')
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1000000:
        _fail('Mesh values must be finite numbers within the supported range.')
    return float(value)


def normalize_influences(values, bone_count):
    """Combine duplicates, keep four strongest, and normalize without zero sums."""
    if not isinstance(values, list) or not 1 <= len(values) <= 32:
        _fail('Supply between one and 32 bone influences per vertex.')
    combined = {}
    for pair in values:
        if not isinstance(pair, list) or len(pair) != 2:
            _fail('Each skin influence needs a bone index and weight.')
        index = _integer(pair[0], bone_count, 'bone index')
        weight = _number(pair[1])
        if not 0 <= weight <= 1:
            _fail('Skin weights must be between zero and one.')
        combined[index] = combined.get(index, 0.) + weight
    strongest = sorted(((i, w) for i, w in combined.items() if w > 0), key=lambda p: (-p[1], p[0]))[:4]
    total = sum(w for _, w in strongest)
    if total <= 1e-12:
        _fail('At least one skin weight must be positive.')
    return [[i, w / total] for i, w in strongest]


def _session(token):
    with model_edits._LOCK:
        return model_edits._session(token)


def _load(raw):
    from . import model_viewer
    import UnityPy
    model_viewer._preflight_bundle(raw)
    class ExplicitEnvironment(UnityPy.Environment):
        def load_file(self, file, parent=None, name=None, is_dependency=False):
            if is_dependency:
                return None
            return super().load_file(file, parent=parent, name=name, is_dependency=is_dependency)
    env = ExplicitEnvironment()
    env.file = env.load_file(raw)
    return env


def _objects(raw):
    env = _load(raw)
    files, objects = {}, {}
    for obj in env.objects:
        files.setdefault(id(obj.assets_file), len(files))
        objects[(files[id(obj.assets_file)], str(obj.path_id))] = obj
    return env, files, objects


def _triangles(tree, count):
    raw = tree.get('m_IndexBuffer', b'')
    if isinstance(raw, list) and len(raw) <= MAX_TRIANGLES * 3 * 4:
        try:
            raw = bytes(raw)
        except (ValueError, TypeError):
            _fail('This mesh has an invalid index buffer.')
    width = 4 if tree.get('m_IndexFormat', 0) == 1 else 2
    if not isinstance(raw, (bytes, bytearray)) or len(raw) % width:
        _fail('This mesh has an invalid index buffer.')
    dtype = '<I' if width == 4 else '<H'
    faces, spans = [], []
    for submesh in tree.get('m_SubMeshes', []):
        first, length = submesh.get('firstByte'), submesh.get('indexCount')
        if (type(first) is not int or type(length) is not int or first < 0 or length < 0 or first % width
                or first + length * width > len(raw) or submesh.get('topology', 0) != 0 or length % 3):
            _fail('UV editing requires valid triangle submeshes.')
        base = submesh.get('baseVertex', 0)
        if type(base) is not int:
            _fail('Invalid mesh base vertex.')
        start = len(faces)
        values = [struct.unpack_from(dtype, raw, first + i * width)[0] + base for i in range(length)]
        if any(v < 0 or v >= count for v in values):
            _fail('A triangle refers to an invalid vertex.')
        faces.extend([values[i:i + 3] for i in range(0, length, 3)])
        spans.append((start, len(faces), base))
    if len(faces) > MAX_TRIANGLES:
        _fail('This mesh exceeds the UV editor triangle limit.')
    return faces, spans, width


def _bone_names(obj, objects, file_index):
    names = []
    for pointer in obj.read_typetree().get('m_Bones', []):
        transform = objects.get((file_index, str(pointer.get('m_PathID')))) if pointer.get('m_FileID') == 0 else None
        game = None
        if transform:
            ptr = transform.read_typetree().get('m_GameObject', {})
            game = objects.get((file_index, str(ptr.get('m_PathID')))) if ptr.get('m_FileID') == 0 else None
        names.append(game.read_typetree().get('m_Name', '') if game else 'Bone ' + str(len(names)))
    return names


def _mesh_records(raw, source):
    env, files, objects = _objects(raw)
    renderers = {}
    for obj in env.objects:
        if obj.type.name == 'SkinnedMeshRenderer':
            ptr = obj.read_typetree().get('m_Mesh', {})
            if ptr.get('m_FileID') == 0:
                key = (files[id(obj.assets_file)], str(ptr.get('m_PathID')))
                renderers.setdefault(key, []).append(obj)
    records = []
    for key, obj in objects.items():
        if obj.type.name != 'Mesh':
            continue
        tree = obj.read_typetree()
        count = tree.get('m_VertexData', {}).get('m_VertexCount', 0)
        identity = {'source': source, 'file': key[0], 'id': key[1]}
        available = type(count) is int and 0 < count <= MAX_MESH_VERTICES
        reason = '' if available else 'This mesh exceeds the UV editor vertex limit or has no inline vertices.'
        bones = []
        linked = renderers.get(key, [])
        if linked:
            bones = _bone_names(linked[0], objects, key[0])
            if any(_bone_names(r, objects, key[0]) != bones for r in linked[1:]):
                available, reason = False, 'This shared mesh has inconsistent skin bindings.'
        records.append((identity, obj, tree, bones, linked, objects, available, reason))
    return env, records


def inspect(token):
    session = _session(token)
    result = []
    for index, source in enumerate(session['sources']):
        _, records = _mesh_records(source['raw'], index)
        for identity, _, tree, bones, _, _, available, reason in records:
            result.append({'mesh': identity, 'name': tree.get('m_Name') or 'Mesh',
                'sourceName': source['name'], 'vertices': tree.get('m_VertexData', {}).get('m_VertexCount', 0),
                'bones': len(bones), 'available': available, 'reason': reason})
    return {'meshes': result, 'originalsPreserved': True}


def _identity(value, session):
    if not isinstance(value, dict) or set(value) != {'source', 'file', 'id'}:
        _fail('Choose a mesh from the original model.')
    source = _integer(value['source'], len(session['sources']), 'mesh source')
    if type(value['file']) is not int or value['file'] < 0 or not isinstance(value['id'], str) or len(value['id']) > 32:
        _fail('Invalid mesh identity.')
    return source


def _record(session, identity, raw=None):
    source = _identity(identity, session)
    env, records = _mesh_records(raw or session['sources'][source]['raw'], source)
    matches = [r for r in records if r[0] == identity]
    if len(matches) != 1 or not matches[0][6]:
        _fail(matches[0][7] if matches else 'The mesh is outside the original model.')
    return env, matches[0]


def _arrays(obj, tree):
    import numpy as np
    from .model_mesh import PreviewMeshHandler
    handler = PreviewMeshHandler(obj.read())
    handler.process()
    positions = np.asarray(handler.m_Vertices, float)
    count = tree['m_VertexData']['m_VertexCount']
    if positions.shape != (count, 3) or not np.isfinite(positions).all():
        _fail('This mesh has unsupported vertex positions.')
    uv = getattr(handler, 'm_UV0', None)
    uv = np.asarray(uv, float)[:, :2] if uv is not None and len(uv) else None
    if uv is not None and (uv.shape != (count, 2) or not np.isfinite(uv).all()):
        uv = None
    weights, indices = getattr(handler, 'm_BoneWeights', None), getattr(handler, 'm_BoneIndices', None)
    return positions, uv, weights, indices


def _texture(linked, objects, file_index, material_index=0):
    from . import decode
    if not linked:
        return None
    pointers = linked[0].read_typetree().get('m_Materials', [])
    for ptr in pointers[material_index:material_index + 1]:
        obj = objects.get((file_index, str(ptr.get('m_PathID')))) if ptr.get('m_FileID') == 0 else None
        if not obj:
            continue
        entries = obj.read_typetree().get('m_SavedProperties', {}).get('m_TexEnvs', [])
        props = dict(entries)
        for name in ('_MainTex', '_BaseMap'):
            texptr = props.get(name, {}).get('m_Texture', {})
            texture = objects.get((file_index, str(texptr.get('m_PathID')))) if texptr.get('m_FileID') == 0 else None
            if not texture or texture.type.name != 'Texture2D':
                continue
            try:
                image = decode._android_image(texture.read(), time.monotonic() + 10)
                with io.BytesIO() as stream:
                    image.save(stream, format='PNG')
                    png = stream.getvalue()
                if len(png) <= 8 * 1024 * 1024:
                    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
            except Exception:
                continue
    return None


def data(token, mesh):
    session = _session(token)
    _, record = _record(session, mesh)
    identity, obj, tree, bones, linked, objects, _, _ = record
    positions, uv, weights, indices = _arrays(obj, tree)
    faces, spans, _ = _triangles(tree, len(positions))
    channels = tree['m_VertexData'].get('m_Channels', [])
    position_writable = bool(channels and channels[0].get('dimension') == 3 and channels[0].get('format') == 0)
    skin = []
    if bones and weights is not None and indices is not None:
        try:
            for ws, ids in zip(weights, indices):
                skin.append(normalize_influences([[int(i), float(w)] for i, w in zip(ids, ws)], len(bones)))
        except MeshToolError:
            skin = []
    skin_writable = bool(skin and (len(tree.get('m_Skin', [])) == len(positions) or
        len(channels) >= 14 and channels[12].get('dimension') == 4 and channels[12].get('format') == 0 and
        channels[13].get('dimension') == 4 and channels[13].get('format') in (6, 8, 10)))
    textures, submeshes, texture_ids, image_bytes = [], [], {}, 0
    pointers = linked[0].read_typetree().get('m_Materials', []) if linked else []
    for index, (first, last, _) in enumerate(spans):
        material_index = min(index, len(pointers) - 1) if pointers else 0
        pointer = pointers[material_index] if pointers else {}
        texture_key = (pointer.get('m_FileID'), pointer.get('m_PathID'))
        material = objects.get((identity['file'], str(pointer.get('m_PathID')))) if pointer.get('m_FileID') == 0 else None
        material_name = material.read_typetree().get('m_Name', '') if material else ''
        if texture_key not in texture_ids:
            image = _texture(linked, objects, identity['file'], material_index) if len(texture_ids) < 32 else None
            if image is not None and image_bytes + len(image) <= 12 * 1024 * 1024:
                texture_ids[texture_key] = len(textures); textures.append(image); image_bytes += len(image)
            else:
                texture_ids[texture_key] = None
        submeshes.append({'index': index, 'name': material_name or 'Material ' + str(index + 1),
            'firstFace': first, 'faceCount': last - first, 'textureIndex': texture_ids[texture_key]})
    first_texture = textures[submeshes[0]['textureIndex']] if submeshes and submeshes[0]['textureIndex'] is not None else None
    return {'mesh': identity, 'name': tree.get('m_Name', 'Mesh'), 'positions': positions.tolist(),
        'uv': uv.tolist() if uv is not None else None, 'triangles': faces, 'bones': bones, 'skin': skin,
        'positionWritable': position_writable, 'skinWritable': skin_writable,
        'texture': first_texture, 'textures': textures, 'submeshes': submeshes, 'coordinates': 'Unity mesh local XYZ',
        'note': 'UV overlaps select every face sharing those texture pixels.'}


def _write_mesh(obj, tree, bones, operation):
    import numpy as np
    from .repo import ensure_repo_on_path
    ensure_repo_on_path()
    from sifas_mesh_baker import stream_layout, write_attr
    count = tree['m_VertexData']['m_VertexCount']
    faces, spans, width = _triangles(tree, count)
    removed = operation.get('deleteFaces', [])
    if not isinstance(removed, list) or len(removed) > len(faces) or any(type(i) is not int for i in removed) or len(set(removed)) != len(removed):
        _fail('Invalid deleted triangle selection.')
    removed = {_integer(i, len(faces), 'triangle index') for i in removed}
    if removed:
        buffer = bytearray()
        for submesh, (first, last, base) in zip(tree['m_SubMeshes'], spans):
            selected = [f for i, f in enumerate(faces[first:last], first) if i not in removed]
            submesh['firstByte'], submesh['indexCount'] = len(buffer), len(selected) * 3
            for face in selected:
                for index in face:
                    buffer.extend(struct.pack('<I' if width == 4 else '<H', index - base))
        tree['m_IndexBuffer'] = bytes(buffer)
    positions, weights = operation.get('positions', []), operation.get('weights', [])
    if not isinstance(positions, list) or not isinstance(weights, list) or len(positions) > MAX_CHANGES or len(weights) > MAX_CHANGES:
        _fail('Too many vertex changes.')
    raw = bytearray(tree['m_VertexData']['m_DataSize'])
    if positions or weights:
        count, channels, stride, start, _ = stream_layout(tree)
        buf = np.frombuffer(raw, np.uint8)
    seen = set()
    if positions:
        if channels[0].get('format') != 0 or channels[0].get('dimension') != 3:
            _fail('Position editing requires Float32 vertex positions.')
        from sifas_mesh_baker import read_attr
        values = read_attr(buf, 0, channels, stride, start, count)
        for row in positions:
            if not isinstance(row, dict) or set(row) != {'vertex', 'position'}:
                _fail('Invalid vertex position change.')
            vertex = _integer(row['vertex'], count, 'vertex index')
            if vertex in seen:
                _fail('Duplicate vertex position change.')
            seen.add(vertex)
            value = row['position']
            if not isinstance(value, list) or len(value) != 3:
                _fail('Vertex positions need three axes.')
            values[vertex] = [_number(v) for v in value]
        write_attr(buf, values, 0, channels, stride, start, count)
        box = tree.get('m_LocalAABB')
        if box:
            low, high = values.min(axis=0), values.max(axis=0)
            for axis, i in zip('xyz', range(3)):
                center, extent = box['m_Center'][axis], abs(box['m_Extent'][axis])
                low[i], high[i] = min(low[i], center - extent), max(high[i], center + extent)
            tree['m_LocalAABB'] = {'m_Center': dict(zip('xyz', map(float, (low + high) / 2))),
                'm_Extent': dict(zip('xyz', map(float, (high - low) / 2)))}
            for submesh in tree.get('m_SubMeshes', []):
                if 'localAABB' in submesh:
                    submesh['localAABB'] = copy.deepcopy(tree['m_LocalAABB'])
    seen = set()
    normalized = []
    for row in weights:
        if not isinstance(row, dict) or set(row) != {'vertex', 'influences'}:
            _fail('Invalid vertex skin change.')
        vertex = _integer(row['vertex'], count, 'vertex index')
        if vertex in seen:
            _fail('Duplicate vertex skin change.')
        seen.add(vertex)
        normalized.append((vertex, normalize_influences(row['influences'], len(bones))))
    if normalized:
        if (len(channels) >= 14 and channels[12].get('dimension') == 4 and channels[12].get('format') == 0
                and channels[13].get('dimension') == 4 and channels[13].get('format') in (6, 8, 10)):
            index_format = {6: ('B', 1), 8: ('H', 2), 10: ('I', 4)}[channels[13]['format']]
            for vertex, values in normalized:
                for slot in range(4):
                    bone, weight = values[slot] if slot < len(values) else (0, 0.)
                    wch, ich = channels[12], channels[13]
                    struct.pack_into('<f', raw, start[wch['stream']] + vertex * stride[wch['stream']] + wch['offset'] + slot * 4, weight)
                    try:
                        struct.pack_into('<' + index_format[0], raw, start[ich['stream']] + vertex * stride[ich['stream']] + ich['offset'] + slot * index_format[1], bone)
                    except struct.error:
                        _fail('This skin index format cannot store the selected bone.')
        elif len(tree.get('m_Skin', [])) == count:
            for vertex, values in normalized:
                for slot in range(4):
                    bone, weight = values[slot] if slot < len(values) else (0, 0.)
                    tree['m_Skin'][vertex]['boneIndex[' + str(slot) + ']'] = bone
                    tree['m_Skin'][vertex]['weight[' + str(slot) + ']'] = weight
        else:
            _fail('This mesh has no writable four-influence skin channel.')
    tree['m_VertexData']['m_DataSize'] = bytes(raw)
    obj.save_typetree(tree)
    return {'deletedFaces': len(removed), 'positions': len(positions), 'weights': len(weights)}



def _check_archive_scope(session):
    from .viewer_archive import _model_header
    import ast
    model_keys = {'costume_file', 'costume_file_ios', 'rina_unmask_costume_file', 'rina_unmask_costume_file_ios'}
    for index, container in enumerate(session['containers']):
        if not any(s['container'] == index and s['member'] is not None for s in session['sources']):
            continue
        selected = {s['member'] for s in session['sources'] if s['container'] == index}
        with zipfile.ZipFile(io.BytesIO(container['raw'])) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                with archive.open(entry) as member:
                    header = member.read(48)
                if _model_header(header, entry.file_size) and entry.filename not in selected:
                    _fail('This ZIP contains alternative model copies. Open an individual Unity bundle to edit mesh vertices or weights.')
                if entry.filename.lower().endswith('.py') and entry.file_size <= 64 * 1024:
                    try:
                        program = ast.parse(archive.read(entry).decode('utf-8-sig'))
                        values = {}
                        for item in program.body:
                            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name) and item.targets[0].id in model_keys:
                                value = ast.literal_eval(item.value)
                                if isinstance(value, str) and value:
                                    values[item.targets[0].id] = value
                        if len(set(values.values())) > 1:
                            _fail('Mesh correspondence between platform or Rina variants is not verified. Open an individual Unity bundle before mesh editing.')
                    except (SyntaxError, UnicodeError, ValueError, TypeError, RecursionError) as error:
                        if isinstance(error, MeshToolError):
                            raise


def export(token, state, output_dir, *, body_state=None):
    session = _session(token)
    if not isinstance(state, dict) or set(state) != {'version', 'meshes'} or type(state.get('version')) is not int or state['version'] != 1:
        _fail('Invalid mesh edit state.')
    try:
        size = len(json.dumps(state, allow_nan=False).encode())
    except (TypeError, ValueError):
        _fail('The mesh edit state contains invalid values.')
    if size > MAX_REQUEST_BYTES or not isinstance(state['meshes'], list) or not 0 <= len(state['meshes']) <= 128:
        _fail('The mesh edit request exceeds the supported limit.')
    _check_archive_scope(session)
    operations, seen = {}, set()
    for operation in state['meshes']:
        if not isinstance(operation, dict) or set(operation) - {'mesh', 'deleteFaces', 'positions', 'weights'}:
            _fail('Unsupported mesh edit property.')
        source = _identity(operation.get('mesh'), session)
        key = (source, operation['mesh']['file'], operation['mesh']['id'])
        if key in seen:
            _fail('The same mesh occurs twice in this edit.')
        seen.add(key)
        if not any(operation.get(name) for name in ('deleteFaces', 'positions', 'weights')):
            _fail('Paint or change at least one vertex before saving.')
        operations.setdefault(source, []).append(operation)
    validated_body = None
    if body_state is not None:
        if not isinstance(body_state, dict):
            _fail('The accompanying body edit state must be an object.')
        validated_body = model_edits.validate_state(token, body_state, allow_empty=True)
    if not session['busy'].acquire(blocking=False):
        _fail('This model is already being saved.')
    temporary = None
    try:
        for container in session['containers']:
            if hashlib.sha256(model_edits._read(container['path'])).hexdigest() != container['sha256']:
                _fail('An original model changed after opening. Reopen it before saving.')
        replacements, summary = {}, []
        for index, source in enumerate(session['sources']):
            raw = source['raw']
            if index not in operations:
                if validated_body:
                    raw, _ = model_edits.edit_source_state(session, index, validated_body)
                if raw != source['raw']:
                    replacements[(source['container'], source['member'])] = raw
                continue
            env, records = _mesh_records(raw, index)
            by_key = {(r[0]['file'], r[0]['id']): r for r in records}
            for operation in operations[index]:
                identity = operation['mesh']
                record = by_key.get((identity['file'], identity['id']))
                if record is None or not record[6]:
                    _fail('A selected mesh is unavailable in its source model.')
                result = _write_mesh(record[1], record[2], record[3], operation)
                if operation.get('positions'):
                    box = record[2].get('m_LocalAABB')
                    if box:
                        for renderer in record[4]:
                            render_tree = renderer.read_typetree()
                            field = 'm_AABB' if render_tree.get('m_AABB') is not None else 'm_LocalAABB'
                            bounds = render_tree.get(field)
                            if bounds:
                                for axis in 'xyz':
                                    low = min(bounds['m_Center'][axis] - abs(bounds['m_Extent'][axis]), box['m_Center'][axis] - abs(box['m_Extent'][axis]))
                                    high = max(bounds['m_Center'][axis] + abs(bounds['m_Extent'][axis]), box['m_Center'][axis] + abs(box['m_Extent'][axis]))
                                    bounds['m_Center'][axis], bounds['m_Extent'][axis] = (low + high) / 2, (high - low) / 2
                                renderer.save_typetree(render_tree)
                summary.append({'mesh': identity, **result})
            changed = env.file.save(packer='original')
            if validated_body:
                # Vertex positions and weights are source-local inputs to the
                # body bake. Apply them before evaluating the body transforms,
                # matching the live skinning preview and avoiding overwriting
                # baked positions with unscaled source-local coordinates.
                context = dict(session); context['sources'] = list(session['sources'])
                context['sources'][index] = dict(source, raw=changed)
                changed, _ = model_edits.edit_source_state(context, index, validated_body)
            # Parse each actual serialized output before publishing it.
            _, reloaded = _mesh_records(changed, index)
            checked = {(r[0]['file'], r[0]['id']): r for r in reloaded}
            for operation in operations[index]:
                ident = operation['mesh']; record = checked[(ident['file'], ident['id'])]
                _triangles(record[2], record[2]['m_VertexData']['m_VertexCount'])
            replacements[(source['container'], source['member'])] = changed
        root = model_edits._safe_root(output_dir)
        temporary = Path(tempfile.mkdtemp(prefix='.mesh-edit-', dir=root))
        (temporary / 'models').mkdir(); (temporary / 'originals').mkdir()
        names, used = [], set()
        for index, container in enumerate(session['containers']):
            name = container['name']
            while name.casefold() in used:
                name = str(index) + '-' + name
            used.add(name.casefold()); names.append(name)
            (temporary / 'originals' / name).write_bytes(container['raw'])
            updates = {member: raw for (ci, member), raw in replacements.items() if ci == index}
            output = temporary / 'models' / name
            if None in updates:
                output.write_bytes(updates[None])
            elif updates:
                with zipfile.ZipFile(io.BytesIO(container['raw'])) as incoming, zipfile.ZipFile(output, 'w') as outgoing:
                    outgoing.comment = incoming.comment
                    for entry in incoming.infolist():
                        outgoing.writestr(copy.copy(entry), updates.pop(entry.filename, incoming.read(entry)))
                    if updates:
                        _fail('A mesh source is missing from its original costume archive.')
            else:
                output.write_bytes(container['raw'])
        recipe = {'version': 1, 'tool': 'mesh-tools', 'sources': [c['sha256'] for c in session['containers']], 'state': state, 'bodyState': validated_body}
        (temporary / 'mesh-recipe.json').write_text(json.dumps(recipe, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        for container in session['containers']:
            if hashlib.sha256(model_edits._read(container['path'])).hexdigest() != container['sha256']:
                _fail('An original model changed while saving. No output was published.')
        final = root / ('mesh-edit-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(4))
        temporary.rename(final); temporary = None
        return {'preview_paths': [str(final / 'models' / n) for n in names],
            'output_paths': [str(final / 'models' / n) for n in names] + [str(final / 'mesh-recipe.json')],
            'original_paths': [str(final / 'originals' / n) for n in names],
            'summary': summary, 'originals_preserved': True}
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        session['busy'].release()
