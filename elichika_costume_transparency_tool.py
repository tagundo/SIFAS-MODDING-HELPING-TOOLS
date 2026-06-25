#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
elichika_costume_transparency_tool.py
=====================================
One tool to make a SIFAS costume's skirt see-through (legs visible through it)
on an elichika server, for ANY live — GUI + CLI.

It does the two things that were proven to actually work:

  (1) SHADER: install a transparent member-body shader (Hidden/AS/Member/Main)
      so the skirt alpha-blends and you can see the legs/body behind it.
      Works per-platform (iOS = Metal, Android = GLES) because the compiled
      shader differs; the tool installs the bundle you give it to the matching
      platform DBs. The member shader's asset_path in elichika is an opaque
      token (e.g. a hash), so the tool finds it automatically by decrypting the
      shader packs and matching the shader name 'Hidden/AS/Member/Main'.

  (2) PER-LIVE FIX: set  m_live_visible_definition.live_enable_skin_merge = 0
      for the live(s) you choose.  When skin-merge is on, the body-mesh merge
      (MergeAndCombineBodyMesh) drops the thigh/pelvis bone weights, so those
      parts vanish behind the skirt.  Turning it off keeps the geometry, so the
      legs render correctly through the transparent skirt.  You pick a live by
      its song id (e.g. 2055 -> live_m_id 12055, looked up in m_live), by
      live_m_id directly, or "ALL".

Run it from anywhere; point it at your elichika root (the folder with
config.json and assets/db/...).  Backups are made before any write.

Dependencies: UnityPy (for the shader step). The per-live fix needs only sqlite3.
"""

import os
import re
import sys
import glob
import json
import time
import zlib
import shutil
import sqlite3
import hashlib
import argparse


# --------------------------------------------------------------------------- #
# XOR stream crypto (game pack cipher). encrypt == decrypt (symmetric).
# key0 = 12345 fixed; key1/key2 from the DB row (0 for our single-asset packs).
# --------------------------------------------------------------------------- #
XOR_KEY0 = 12345


def manipulate(buf, k0, k1, k2):
    for i in range(len(buf)):
        buf[i] ^= ((k1 ^ k0 ^ k2) >> 24 & 0xFF)
        k0 = (0x343FD * k0 + 0x269EC3) & 0xFFFFFFFF
        k1 = (0x343FD * k1 + 0x269EC3) & 0xFFFFFFFF
        k2 = (0x343FD * k2 + 0x269EC3) & 0xFFFFFFFF


def xor_bytes(data, k1=0, k2=0):
    b = bytearray(data)
    manipulate(b, XOR_KEY0, int(k1 or 0), int(k2 or 0))
    return bytes(b)


# --------------------------------------------------------------------------- #
# sqlite helpers
# --------------------------------------------------------------------------- #
def table_exists(cur, t):
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,))
    return cur.fetchone() is not None


def columns(cur, t):
    cur.execute('PRAGMA table_info("%s")' % t)
    return [r[1] for r in cur.fetchall()]


def asset_dbs(root):
    return sorted(glob.glob(os.path.join(root, "assets/db/**/asset_*.db"), recursive=True))


def masterdata_dbs(root):
    return sorted(glob.glob(os.path.join(root, "assets/db/**/masterdata.db"), recursive=True)) \
        or sorted(glob.glob(os.path.join(root, "assets/db/**/*master*.db"), recursive=True))


def db_platform(path):
    b = os.path.basename(path)
    if "_i_" in b or b.startswith("asset_i"):
        return "ios"
    if "_a_" in b or b.startswith("asset_a"):
        return "android"
    return "unknown"


def backup(path, log):
    dst = path + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy(path, dst)
    # WAL-mode DBs keep committed-but-uncheckpointed data in sidecars; copy them
    # too so the backup is a consistent, restorable snapshot.
    for ext in ("-wal", "-shm"):
        if os.path.exists(path + ext):
            shutil.copy(path + ext, dst + ext)
    log("  backup -> " + os.path.basename(dst))


# --------------------------------------------------------------------------- #
# pack location + the robust "find the member-Main shader row" logic
# --------------------------------------------------------------------------- #
def pack_dirs(root):
    d = [os.path.join(root, x) for x in ("static", "packs", "cache", ".")]
    d += glob.glob(os.path.join(root, "static", "*"))
    return d


def find_pack_file(root, pack_name):
    for d in pack_dirs(root):
        p = os.path.join(d, pack_name)
        if os.path.isfile(p):
            return p
    return None


def decrypt_section(pack_path, head, size, k1, k2):
    with open(pack_path, "rb") as f:
        f.seek(int(head or 0))
        data = bytearray(f.read(int(size) if size else -1))
    manipulate(data, XOR_KEY0, int(k1 or 0), int(k2 or 0))
    return bytes(data)


def shader_names_of(bundle_bytes):
    import UnityPy
    env = UnityPy.load(bundle_bytes)
    out = []
    for o in env.objects:
        if o.type.name == "Shader":
            try:
                out.append(o.read().m_ParsedForm.m_Name)
            except Exception:
                pass
    return out


def find_member_main(root, asset_db, want_shader="Hidden/AS/Member/Main", log=print):
    """Return (asset_path, pack_name, head, size, key1, key2) of the row whose
    decrypted pack contains `want_shader`, scanning a single asset DB.
    Also matches rows already pointing at one of our CRC-prefixed packs."""
    con = sqlite3.connect(asset_db)
    try:
        cur = con.cursor()
        if not table_exists(cur, "shader"):
            return None
        rows = cur.execute(
            "SELECT asset_path,pack_name,head,size,key1,key2 FROM shader").fetchall()
    finally:
        con.close()
    # fast path: a row already on one of our packs (8 hex prefix) is *probably*
    # our member shader — but VERIFY by decrypting it (don't blindly trust the
    # prefix, in case other shaders were also modded).
    for ap, pn, head, size, k1, k2 in rows:
        if pn and re.match(r'^[0-9a-f]{8}', str(pn)):
            pp = find_pack_file(root, pn)
            if not pp:
                continue
            try:
                data = decrypt_section(pp, head, size, k1, k2)
                if data[:7] == b"UnityFS" and want_shader in shader_names_of(data):
                    return (ap, pn, head, size, k1, k2)
            except Exception:
                pass
    # robust path: decrypt each pack, read shader name
    for ap, pn, head, size, k1, k2 in rows:
        pp = find_pack_file(root, pn)
        if not pp:
            continue
        try:
            data = decrypt_section(pp, head, size, k1, k2)
            if data[:7] != b"UnityFS":
                continue
            if want_shader in shader_names_of(data):
                return (ap, pn, head, size, k1, k2)
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# shader: apply the transparent-skirt blend + install
# --------------------------------------------------------------------------- #
def apply_transparent_blend(src_bytes):
    """Return new bundle bytes with the member Main color pass switched to
    alpha blending (SrcAlpha / OneMinusSrcAlpha) so the skirt becomes
    see-through to the legs.  ZWrite kept ON, CAB preserved."""
    import UnityPy
    env = UnityPy.load(src_bytes)

    def sv(d, v):
        if isinstance(d, dict) and "val" in d:
            d["val"] = float(v)

    changed = 0
    for o in env.objects:
        if o.type.name != "Shader":
            continue
        t = o.read_typetree()
        pf = t.get("m_ParsedForm") or {}
        for ss in pf.get("m_SubShaders", []):
            for p in ss.get("m_Passes", []):
                rt = (p.get("m_State") or {}).get("rtBlend0") or {}
                if not rt:
                    continue
                sv(rt.get("srcBlend", {}), 5)        # SrcAlpha
                sv(rt.get("destBlend", {}), 10)       # OneMinusSrcAlpha
                sv(rt.get("srcBlendAlpha", {}), 1)    # One
                sv(rt.get("destBlendAlpha", {}), 10)  # OneMinusSrcAlpha
                changed += 1
        o.save_typetree(t)
    if not changed:
        raise RuntimeError("no shader pass found to edit")
    return env.file.save(packer="lz4")


def register_pack(cur, pack_name, size, old_pack=None):
    """Register the new pack as a downloadable 'main' package and bump the
    client-facing version so it re-syncs.  This mirrors elichika's own resolver:
      - m_asset_package_mapping.package_key == 'main' is what marks a pack as
        downloadable (asset_database.go: PackIsMainPackage);
      - the client re-syncs when the 'main' row of m_asset_package gets a fresh
        version + pack_num (asset_database_update.go).
    Registering under any other package_key, or failing to bump 'main', means the
    client never fetches the new pack — the shader silently won't load."""
    # carry over the category from the original member pack's 'main' mapping
    category = 1
    if old_pack and table_exists(cur, "m_asset_package_mapping"):
        r = cur.execute("SELECT category FROM m_asset_package_mapping "
                        "WHERE pack_name=? ORDER BY (package_key='main') DESC LIMIT 1",
                        (old_pack,)).fetchone()
        if r and r[0] is not None:
            category = r[0]
    if table_exists(cur, "m_asset_pack"):
        if not cur.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack_name,)).fetchone():
            cur.execute("INSERT INTO m_asset_pack (pack_name, auto_delete) VALUES (?, '0')",
                        (pack_name,))
    if table_exists(cur, "m_asset_package_mapping"):
        if cur.execute("SELECT 1 FROM m_asset_package_mapping WHERE package_key='main' AND pack_name=?",
                       (pack_name,)).fetchone():
            cur.execute("UPDATE m_asset_package_mapping "
                        "SET file_size=?, metapack_name=NULL, metapack_offset='0', category=? "
                        "WHERE package_key='main' AND pack_name=?", (size, category, pack_name))
        else:
            cur.execute("INSERT INTO m_asset_package_mapping "
                        "(package_key,pack_name,file_size,metapack_name,metapack_offset,category) "
                        "VALUES ('main',?,?,NULL,'0',?)", (pack_name, size, category))
    # bump the 'main' package version -> client re-syncs and fetches the new pack
    if table_exists(cur, "m_asset_package"):
        fresh = hashlib.sha1(os.urandom(16)).hexdigest()
        cnt = cur.execute("SELECT COUNT(*) FROM m_asset_package_mapping "
                          "WHERE package_key='main'").fetchone()[0]
        cur.execute("REPLACE INTO m_asset_package (package_key,version,pack_num) VALUES ('main',?,?)",
                    (fresh, str(cnt)))


def install_shader(root, bundle_path, platform="ios", make_transparent=True,
                   do_backup=True, asset_path=None, log=print):
    """Install a member-Main shader bundle into elichika for the chosen platform.
    platform: 'ios' | 'android' | 'both'.  The compiled shader is platform-specific
    (iOS=Metal, Android=GLES), so the bundle is written ONLY to DBs whose platform
    matches; an iOS bundle is never written to Android DBs (or vice versa)."""
    with open(bundle_path, "rb") as f:
        raw = f.read()
    if make_transparent:
        raw = apply_transparent_blend(raw)
        log("[shader] applied transparent-skirt blend (SrcAlpha/OneMinusSrcAlpha)")
    size = len(raw)
    enc = xor_bytes(raw, 0, 0)
    pack_name = ("%08x" % (zlib.crc32(raw) & 0xFFFFFFFF)) + "membertransp"
    static = os.path.join(root, "static")
    os.makedirs(static, exist_ok=True)
    with open(os.path.join(static, pack_name), "wb") as f:
        f.write(enc)
    log("[shader] wrote pack static/%s (%d bytes)" % (pack_name, size))

    # member Main asset_path is shared across platforms; find it once (or use override).
    member_ap = asset_path
    if member_ap:
        log("[shader] using provided asset_path = %r" % member_ap)
    else:
        for adb in asset_dbs(root):
            r = find_member_main(root, adb, log=log)
            if r:
                member_ap = r[0]
                log("[shader] member Main asset_path = %r (from %s)" % (member_ap, os.path.basename(adb)))
                break
    if member_ap is None:
        raise RuntimeError("could not locate the member Main shader row in any asset DB "
                           "(no decryptable pack contained 'Hidden/AS/Member/Main'). "
                           "Pass an explicit --asset-path if you know it.")

    want = {"ios", "android"} if platform == "both" else {platform}
    touched = []
    for adb in asset_dbs(root):
        plat = db_platform(adb)
        # only write the bundle to DBs whose platform matches (never cross-install
        # a Metal bundle into a GLES DB, and skip 'unknown'-named DBs entirely)
        if plat not in want:
            continue
        con = sqlite3.connect(adb)
        try:
            cur = con.cursor()
            if not table_exists(cur, "shader"):
                continue
            old = cur.execute("SELECT pack_name FROM shader WHERE asset_path=?",
                              (member_ap,)).fetchone()
            n = cur.execute("UPDATE shader SET pack_name=?, head='0', size=?, key1='0', key2='0' "
                            "WHERE asset_path=?", (pack_name, size, member_ap)).rowcount
            if n:
                if do_backup:
                    backup(adb, log)
                register_pack(cur, pack_name, size, old_pack=(old[0] if old else None))
                con.commit()
                touched.append((os.path.basename(adb), plat))
                log("  [ok] %s [%s]" % (os.path.basename(adb), plat))
        finally:
            con.close()
    # config cdn
    cfg = os.path.join(root, "config.json")
    if os.path.exists(cfg):
        try:
            with open(cfg) as f:
                c = json.load(f)
            if c.get("cdn_server") != "http://127.0.0.1:8080/static":
                c["cdn_server"] = "http://127.0.0.1:8080/static"
                with open(cfg, "w") as f:
                    json.dump(c, f, indent=4)
                log("[config] cdn_server -> local")
        except Exception:
            pass
    if not touched:
        log("[shader] WARNING: no %s DB was updated (member row not found in a matching "
            "platform DB). Nothing applied — check --platform and --asset-path."
            % ("/".join(sorted(want))))
    else:
        log("[shader] updated %d DB(s). Re-sync the client to apply." % len(touched))
    return touched


# --------------------------------------------------------------------------- #
# masterdata: per-live skin-merge fix
# --------------------------------------------------------------------------- #
VISDEF = "m_live_visible_definition"
SENTINEL_LIVE_M_ID = 9999  # default-template row; never overwrite it


def resolve_live_m_id(cur, key, log=print):
    """key may be a live_m_id (e.g. 12055), a song id (2055 -> 12055 via m_live),
    or a string. Returns the matching live_m_id, or None."""
    s = str(key).strip()
    # direct live_m_id present in visible_definition or m_live
    if s.isdigit():
        n = int(s)
        if table_exists(cur, VISDEF) and cur.execute(
                "SELECT 1 FROM %s WHERE live_m_id=?" % VISDEF, (n,)).fetchone():
            return n
        if table_exists(cur, "m_live"):
            r = cur.execute("SELECT live_id FROM m_live WHERE live_id=?", (n,)).fetchone()
            if r:
                # warn if this same number ALSO matches a different live by music_id
                m = cur.execute("SELECT live_id FROM m_live WHERE music_id=?", (n,)).fetchone()
                if m and m[0] != r[0]:
                    log("  [warn] %r matches both live_id=%s and music_id-of-live=%s; "
                        "using live_id=%s (pass the live_m_id directly to disambiguate)"
                        % (s, r[0], m[0], r[0]))
                return r[0]
            # treat as song/music id
            r = cur.execute("SELECT live_id FROM m_live WHERE music_id=?", (n,)).fetchone()
            if r:
                return r[0]
    # name / so#### lookup
    if table_exists(cur, "m_live"):
        for col in ("name", "pronunciation"):
            if col in columns(cur, "m_live"):
                r = cur.execute("SELECT live_id FROM m_live WHERE %s LIKE ?" % col,
                                ("%" + s + "%",)).fetchone()
                if r:
                    return r[0]
    return None


def default_mixer(cur):
    if table_exists(cur, VISDEF):
        r = cur.execute("SELECT live_mixer_base_mode FROM %s WHERE live_m_id=?" % VISDEF,
                        (SENTINEL_LIVE_M_ID,)).fetchone()
        if r and r[0] is not None:
            return r[0]
    return 1


def fix_live(root, keys, skin_merge=0, safe_swing=None, do_backup=True, log=print):
    """For each key (live id / song id / name / 'ALL'), upsert the visible
    definition with live_enable_skin_merge=skin_merge. safe_swing: None=leave,
    or 0/1 to also set safe_swing_bone."""
    total = []
    for mdb in masterdata_dbs(root):
        con = sqlite3.connect(mdb)
        try:
            cur = con.cursor()
            if not table_exists(cur, VISDEF):
                continue
            cols = columns(cur, VISDEF)
            if "live_enable_skin_merge" not in cols:
                log("  [skip] %s has no live_enable_skin_merge column" % os.path.basename(mdb))
                continue
            # resolve targets
            targets = []
            for key in keys:
                if str(key).strip().upper() == "ALL":
                    if table_exists(cur, "m_live"):
                        targets += [r[0] for r in cur.execute("SELECT live_id FROM m_live").fetchall()]
                    targets += [r[0] for r in cur.execute("SELECT live_m_id FROM %s" % VISDEF).fetchall()]
                else:
                    lid = resolve_live_m_id(cur, key, log=log)
                    if lid is None:
                        log("  [warn] %s: could not resolve live %r" % (os.path.basename(mdb), key))
                        continue
                    targets.append(lid)
            # never touch the 9999 sentinel/default-template row (default_mixer reads it)
            targets = sorted(set(t for t in targets if t != SENTINEL_LIVE_M_ID))
            if not targets:
                continue
            if do_backup:
                backup(mdb, log)
            mixer = default_mixer(cur)
            done = 0
            failed = 0
            for lid in targets:
                exists = cur.execute("SELECT 1 FROM %s WHERE live_m_id=?" % VISDEF, (lid,)).fetchone()
                try:
                    if exists:
                        sets = ["live_enable_skin_merge=?"]
                        vals = [skin_merge]
                        if safe_swing is not None:
                            sets.append("safe_swing_bone=?"); vals.append(safe_swing)
                        cur.execute("UPDATE %s SET %s WHERE live_m_id=?" % (VISDEF, ",".join(sets)),
                                    (*vals, lid))
                    else:
                        # schema-driven INSERT: only set columns that actually exist, so we
                        # don't break on schema variants (extra cols just take their default)
                        row = {"live_m_id": lid,
                               "live_enable_skin_merge": skin_merge,
                               "live_mixer_base_mode": mixer,
                               "safe_swing_bone": safe_swing}
                        use = [c for c in cols if c in row]
                        cur.execute("INSERT INTO %s (%s) VALUES (%s)"
                                    % (VISDEF, ",".join(use), ",".join("?" * len(use))),
                                    tuple(row[c] for c in use))
                    done += 1
                except sqlite3.Error as e:
                    failed += 1
                    log("  [warn] %s: live_m_id=%s failed: %s" % (os.path.basename(mdb), lid, e))
            con.commit()
            total.append((os.path.basename(mdb), done))
            msg = "  [ok] %s: %d live(s) set skin_merge=%d" % (os.path.basename(mdb), done, skin_merge)
            if failed:
                msg += " (%d failed)" % failed
            log(msg)
        finally:
            con.close()
    log("[live-fix] done. Re-sync the client (masterdata) to apply.")
    return total


def list_lives(root):
    out = []
    for mdb in masterdata_dbs(root):
        con = sqlite3.connect(mdb)
        try:
            cur = con.cursor()
            if not table_exists(cur, "m_live"):
                continue
            cols = columns(cur, "m_live")
            namec = "name" if "name" in cols else None
            musc = "music_id" if "music_id" in cols else None
            sel = "live_id" + ((",%s" % musc) if musc else "") + ((",%s" % namec) if namec else "")
            for r in cur.execute("SELECT %s FROM m_live ORDER BY live_id" % sel).fetchall():
                out.append(r)
            break
        finally:
            con.close()
    return out


# --------------------------------------------------------------------------- #
# self-test (mock DBs, exercises live-fix + asset_path finding logic)
# --------------------------------------------------------------------------- #
def selftest():
    import tempfile
    root = tempfile.mkdtemp(prefix="costume_tool_test_")
    os.makedirs(os.path.join(root, "assets/db/gl"))
    print("=== self-test in", root, "===")
    md = os.path.join(root, "assets/db/gl/masterdata.db")
    con = sqlite3.connect(md); c = con.cursor()
    c.execute("CREATE TABLE m_live(live_id INT, music_id INT, name TEXT)")
    c.execute("INSERT INTO m_live VALUES (12055,2055,'k.song_name_so2055')")
    c.execute("INSERT INTO m_live VALUES (12056,2056,'k.song_name_so2056')")
    c.execute("CREATE TABLE %s(live_m_id INT, safe_swing_bone INT, live_mixer_base_mode INT, live_enable_skin_merge INT)" % VISDEF)
    c.execute("INSERT INTO %s VALUES (9999,NULL,1,0)" % VISDEF)
    c.execute("INSERT INTO %s VALUES (12056,1,2,1)" % VISDEF)  # existing row
    con.commit(); con.close()

    print("\n-- resolve + fix so2055 (no row -> insert) by song id 2055 --")
    fix_live(root, ["2055"], skin_merge=0)
    print("-- fix so2056 (existing row -> update) by live_m_id --")
    fix_live(root, ["12056"], skin_merge=0)

    con = sqlite3.connect(md); c = con.cursor()
    r55 = c.execute("SELECT * FROM %s WHERE live_m_id=12055" % VISDEF).fetchone()
    r56 = c.execute("SELECT * FROM %s WHERE live_m_id=12056" % VISDEF).fetchone()
    con.close()
    ok = (r55 is not None and r55[3] == 0) and (r56 is not None and r56[3] == 0)
    print("  so2055 row:", r55, " so2056 row:", r56)
    print("  [%s] both lives have skin_merge=0; existing mixer kept (%s)" %
          ("OK" if ok else "FAIL", r56[2] if r56 else "?"))
    print("  lives listed:", list_lives(root))
    shutil.rmtree(root, ignore_errors=True)
    print("=== self-test", "PASSED" if ok else "FAILED", "===")
    return ok


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, scrolledtext
    except ImportError:
        sys.stderr.write("tkinter not available; use the CLI (see --help)\n")
        sys.exit(2)

    root = tk.Tk(); root.title("elichika Costume Transparency Tool"); root.geometry("860x680")
    rootvar = tk.StringVar(value=os.getcwd())
    bundlevar = tk.StringVar()
    platvar = tk.StringVar(value="ios")
    transpvar = tk.BooleanVar(value=True)
    livevar = tk.StringVar(value="ALL")
    allvar = tk.BooleanVar(value=True)
    safevar = tk.BooleanVar(value=False)

    top = ttk.Frame(root, padding=8); top.pack(fill="x")
    ttk.Label(top, text="elichika root:").grid(row=0, column=0, sticky="w")
    ttk.Entry(top, textvariable=rootvar, width=64).grid(row=0, column=1, padx=4)
    ttk.Button(top, text="Browse", command=lambda: rootvar.set(
        filedialog.askdirectory() or rootvar.get())).grid(row=0, column=2)

    log = scrolledtext.ScrolledText(root, height=20, font=("TkFixedFont", 9))

    def L(*a):
        log.insert("end", " ".join(str(x) for x in a) + "\n"); log.see("end"); root.update_idletasks()

    nb = ttk.Notebook(root); nb.pack(fill="x", padx=8, pady=4)

    # --- shader tab ---
    f1 = ttk.Frame(nb, padding=8); nb.add(f1, text="1) Transparent shader")
    ttk.Label(f1, text="Member-Main shader bundle (.unity):").grid(row=0, column=0, sticky="w")
    ttk.Entry(f1, textvariable=bundlevar, width=52).grid(row=0, column=1, padx=4)
    ttk.Button(f1, text="Browse", command=lambda: bundlevar.set(
        filedialog.askopenfilename(filetypes=[("Unity", "*.unity *.unity3d"), ("All", "*.*")]) or bundlevar.get())
    ).grid(row=0, column=2)
    ttk.Label(f1, text="Platform of this bundle:").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Combobox(f1, textvariable=platvar, values=["ios", "android"], width=10, state="readonly").grid(row=1, column=1, sticky="w")
    ttk.Checkbutton(f1, text="apply transparent-skirt blend (uncheck if bundle is already edited)",
                    variable=transpvar).grid(row=2, column=0, columnspan=3, sticky="w")

    def do_shader():
        try:
            install_shader(rootvar.get(), bundlevar.get(), platform=platvar.get(),
                           make_transparent=transpvar.get(), log=L)
            messagebox.showinfo("Done", "Shader installed. Re-sync the client.")
        except Exception as e:
            L("[error]", e); messagebox.showerror("Error", str(e))
    ttk.Button(f1, text="Install shader", command=do_shader).grid(row=3, column=0, pady=8, sticky="w")
    ttk.Label(f1, text="(iOS uses asset_i DBs, Android asset_a. Install once per platform you play.)",
              foreground="#666").grid(row=4, column=0, columnspan=3, sticky="w")

    # --- per-live fix tab ---
    f2 = ttk.Frame(nb, padding=8); nb.add(f2, text="2) Per-live leg fix")
    livefield = ttk.Entry(f2, textvariable=livevar, width=52)

    def sync_all():
        if allvar.get():
            livevar.set("ALL"); livefield.configure(state="disabled")
        else:
            livefield.configure(state="normal")
    ttk.Checkbutton(f2, text="All lives  (recommended — applies to every live)",
                    variable=allvar, command=sync_all).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(f2, text="…or specific live(s):  song id (2055), live_m_id (12055), name — comma separated").grid(
        row=1, column=0, columnspan=3, sticky="w")
    livefield.grid(row=2, column=0, columnspan=2, padx=4, pady=4, sticky="w")
    ttk.Checkbutton(f2, text="also set safe_swing_bone=0 (usually not needed)", variable=safevar).grid(
        row=3, column=0, columnspan=3, sticky="w")
    sync_all()

    def do_live():
        keys = ["ALL"] if allvar.get() else [k.strip() for k in livevar.get().split(",") if k.strip()]
        if not keys:
            messagebox.showinfo("Live", "Enter at least one live (e.g. 2055 or ALL)"); return
        try:
            fix_live(rootvar.get(), keys, skin_merge=0,
                     safe_swing=(0 if safevar.get() else None), log=L)
            messagebox.showinfo("Done", "Per-live fix applied. Re-sync the client (masterdata).")
        except Exception as e:
            L("[error]", e); messagebox.showerror("Error", str(e))
    ttk.Button(f2, text="Apply skin_merge=0", command=do_live).grid(row=4, column=0, pady=8, sticky="w")

    def do_listlives():
        for r in list_lives(rootvar.get())[:300]:
            L("  live:", r)
    ttk.Button(f2, text="List lives", command=do_listlives).grid(row=4, column=1, sticky="w")
    ttk.Label(f2, text="(skin_merge=0 keeps thigh/pelvis geometry so legs render through the skirt.)",
              foreground="#666").grid(row=5, column=0, columnspan=3, sticky="w")

    log.pack(fill="both", expand=True, padx=8, pady=6)
    root.mainloop()


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="elichika costume transparency tool (shader + per-live leg fix)")
    ap.add_argument("-r", "--root", default=".", help="elichika root")
    ap.add_argument("--shader", metavar="BUNDLE", help="install transparent member shader from BUNDLE")
    ap.add_argument("--platform", choices=["ios", "android", "both"], default="ios")
    ap.add_argument("--no-transparent", action="store_true", help="bundle is already edited; don't re-blend")
    ap.add_argument("--asset-path", default=None, help="member shader asset_path override (if auto-detect fails)")
    ap.add_argument("--fix-live", metavar="LIVES", nargs="?", const="ALL",
                    help="comma-separated live ids/song ids/names, or ALL. "
                         "Bare --fix-live (no value) = ALL (default).")
    ap.add_argument("--safe-swing-off", action="store_true", help="also set safe_swing_bone=0")
    ap.add_argument("--list-lives", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if a.list_lives:
        for r in list_lives(a.root):
            print(r)
        return
    did = False
    changed = False
    if a.shader:
        touched = install_shader(a.root, a.shader, platform=a.platform,
                                 make_transparent=not a.no_transparent,
                                 asset_path=a.asset_path, log=print)
        did = True
        changed = changed or bool(touched)
    if a.fix_live:
        total = fix_live(a.root, [k.strip() for k in a.fix_live.split(",") if k.strip()],
                         skin_merge=0, safe_swing=(0 if a.safe_swing_off else None), log=print)
        did = True
        changed = changed or any(n for _, n in total)
    if not did:
        run_gui()
        return
    # non-zero exit if an action was requested but nothing was actually changed
    if not changed:
        print("[done] nothing was changed (no matching DB/live). See warnings above.")
        sys.exit(3)


if __name__ == "__main__":
    main()
