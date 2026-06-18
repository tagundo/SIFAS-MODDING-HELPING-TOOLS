"""`python -m webtools` entry point: start the local WebUI server.

Binds to loopback by default (no LAN exposure on a phone), auto-opens a browser
on desktop, and prints Termux-friendly hints.
"""
import argparse
import threading
import webbrowser

from webtools.core.sukusta import default_sukusta_dir, is_termux


def _banner(url):
    print("=" * 60)
    print(" SIFAS modding tools - local WebUI")
    print("=" * 60)
    print(f" Open:        {url}")
    print(f" Extracted:   {default_sukusta_dir('extracted')}")
    print(f" Modded:      {default_sukusta_dir('modded')}")
    if is_termux():
        print(" Termux notes:")
        print("   - texture import / thumbnails need Pillow: pkg install python-pillow")
        print("   - if a thumbnail can't decode it simply shows a placeholder")
        print(f"   - open the URL above in your browser app")
    print(" Press Ctrl+C to stop.")
    print("=" * 60)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="webtools", description="Local-first WebUI for the SIFAS modding tools")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default 127.0.0.1; use 0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, default=8770, help="port (default 8770)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not auto-open a browser")
    args = parser.parse_args(argv)

    # import here so --help works even before optional deps exist
    from webtools.server import serve

    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{display_host}:{args.port}/"
    _banner(url)

    if not args.no_browser and not is_termux():
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    serve(args.host, args.port)


if __name__ == "__main__":
    main()
