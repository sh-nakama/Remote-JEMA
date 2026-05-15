import httpx, io, zipfile
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'
for y in [2023, 2024, 2025, 2026]:
    u = f'https://powergrid.chuden.co.jp/denki_yoho_content_data/eria_jukyu_{y}.zip'
    r = httpx.get(u, headers={'User-Agent': ua}, timeout=30, follow_redirects=True)
    print(y, r.status_code, len(r.content))
    if r.status_code == 200 and r.content[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        print(' ', names[:5], '...', len(names), 'files')
        with z.open(names[0]) as f:
            head = f.read(500)
        print('  head:', head[:200])
