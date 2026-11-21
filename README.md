# AwasLewat

Aplikasi komuter untuk pengguna **KRL Commuter Line** dan **Transjakarta** (BRT, Metrotrans, Mikrotrans) di Jabodetabek. Isinya peta rute, pencarian halte dan tempat, rute multimoda yang memperhitungkan kemacetan, dan alarm agar tidak kelewatan stasiun atau halte tujuan.

Proyek kelompok mata kuliah Dasar-Dasar Pemrograman 1 (DDP-1), Fasilkom UI, Gasal 2026/2027.

## Latar belakang

Komuter yang menggabungkan KRL dan Transjakarta harus berpindah-pindah aplikasi dalam satu perjalanan. Selain itu:

- Titik awal dan tujuan jarang tepat di halte, dan halte terdekat belum tentu yang terbaik bila jalan ke sana macet parah.
- Kebutuhan tiap orang berbeda: ada yang ingin cepat, murah, sedikit ganti kendaraan, atau tidak berdesakan.
- Komuter jarak jauh yang tertidur di perjalanan berisiko kelewatan stasiun tujuan.

## Fitur

| Fitur | Status |
| --- | --- |
| Peta OSM terbatas wilayah Jabodetabek + lokasi pengguna | Direncanakan |
| Jalur KRL dan koridor Transjakarta dengan warna resmi | Direncanakan |
| Pencarian jalur, halte, dan tempat umum | Direncanakan |
| Rute tercepat dan termurah dari titik mana pun | Mesin rute dan endpoint `POST /route` selesai (dengan data uji); menunggu data asli |
| Rute paling sedikit transit dan paling lengang | Mesin rute selesai (dengan data uji dan tabel kepadatan sementara) |
| Pengalihan halte naik/turun saat akses macet parah | Logika dan klien OSRM/TomTom selesai (diuji dengan respons tiruan) |
| Penggabungan hasil rute yang sama menjadi satu kartu | Selesai |
| Alarm tujuan yang tetap berbunyi saat HP dalam mode senyap | Direncanakan |

## Arsitektur

Semua logika utama ditulis dalam **Python**. Klien Android hanya menampilkan hasil dan menjalankan alarm.

```
┌────────────────────┐  JSON  ┌──────────────────────────┐     ┌─────────────────────┐
│ Klien Android      │◄──────►│ Backend Python (FastAPI) │────►│ OSRM, TomTom,       │
│ (Kotlin, MapLibre) │        │ - mesin rute             │     │ Photon, Nominatim   │
│ - peta, UI, alarm  │        │ - pencarian              │     └─────────────────────┘
└────────────────────┘        └────────────▲─────────────┘
                                           │ data rute + halte
                              ┌────────────┴─────────────┐     ┌─────────────────────┐
                              │ Pipeline data Python     │◄────│ GTFS Transjakarta,  │
                              │ GTFS + OSM → JSON        │     │ OpenStreetMap (KRL) │
                              └──────────────────────────┘     └─────────────────────┘
```

## Struktur repository

```
backend/
  api/          endpoint /lines dan /search
  schemas/      skema request/response (Pydantic)
  routing/      mesin rute: graf, Dijkstra, tarif, planner
pipeline/       pengolah data GTFS/OSM
data/
  processed/    hasil pipeline yang dibaca backend
android/        klien Android (Kotlin)
tests/
  routing/      unit test mesin rute + 10 skenario
  api/          test integrasi API
docs/           diagram dan dokumentasi pendukung
```

## Mesin rute

Modul `backend/routing/` mencari rute dari titik sembarang ke titik sembarang.

1. **Halte kandidat.** Ambil maksimal 3 halte terdekat dalam radius 2 km dari titik awal dan tujuan (jarak haversine).
2. **Akses ke halte.** Jalan kaki untuk jarak ≤ 1 km, berkendara bila lebih jauh. Durasi akses berkendara memakai kecepatan lalu lintas saat ini. Bila layanan eksternal gagal, dipakai perkiraan haversine × 1,3.
3. **Node virtual.** Titik awal dihubungkan ke semua halte kandidat, dan semua halte kandidat tujuan dihubungkan ke titik tujuan. Dengan begitu satu kali pencarian langsung memilih pasangan halte terbaik.
4. **Dijkstra buatan sendiri** (`heapq`). State pencarian = (halte, rute yang sedang dinaiki, area berbayar), agar waktu tunggu, transit, dan tarif bisa dihitung dengan benar.
5. **Fungsi biaya per kategori.**
   - Tercepat: waktu tempuh × pengali macet + waktu tunggu.
   - Termurah: total tarif, dengan waktu sebagai penentu bila tarif sama.
   - Paling sedikit transit: penalti besar setiap naik kendaraan, ditambah waktu.
   - Paling lengang: waktu perjalanan × pengali kepadatan per jam, ditambah waktu tunggu.
6. **Deduplikasi.** Rute dengan urutan naik/turun kendaraan yang sama digabung menjadi satu kartu dengan beberapa badge.

### Aturan tarif yang dipakai

| Moda | Tarif |
| --- | --- |
| KRL | Rp3.000 untuk 25 km pertama + Rp1.000 per 10 km berikutnya, dari jarak stasiun tap-in ke tap-out. Ganti jalur di stasiun yang sama tidak bayar lagi. |
| Transjakarta (BRT, Metrotrans) | Rp3.500 per naik; Rp2.000 pukul 05.00–06.59. Transfer di halte yang sama tidak bayar lagi (dapat diatur). |
| Mikrotrans | Rp0 |

Semua angka tarif disimpan sebagai konfigurasi sehingga mudah diubah bila aturan berganti.

## Cara menjalankan

Butuh Python 3.11 atau lebih baru.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

**Linux/macOS:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Menjalankan test dan pemeriksaan gaya kode:

```bash
pytest -q
ruff check .
ruff format --check .
```

Test tidak membutuhkan internet; semua layanan eksternal disimulasikan.

### API key TomTom

Data lalu lintas memakai TomTom Traffic (gratis, daftar di developer.tomtom.com). Simpan key sebagai environment variable, **jangan** ditulis di kode atau di-commit:

```powershell
$env:TOMTOM_API_KEY = "isi-key-kamu"
```

Tanpa key, aplikasi tetap berjalan: akses berkendara memakai perkiraan kecepatan tetap dan ditandai "lalu lintas tidak diketahui".

## Sumber data

| Sumber | Dipakai untuk |
| --- | --- |
| [GTFS Transjakarta](https://mobilitydatabase.org/feeds/gtfs/mdb-1909) | Rute, halte, dan warna koridor Transjakarta |
| OpenStreetMap | Jalur dan stasiun KRL, peta dasar |
| OSRM | Jalur dan durasi akses ke halte |
| TomTom Traffic | Kecepatan lalu lintas |

Peta dan data jalur © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright). Data lalu lintas © TomTom.

## Keterbatasan

- Data uji `tests/routing/fixtures/jabodetabek_small.json` memakai koordinat **perkiraan** dan hanya mencakup Commuter Line Bogor, Commuter Line Cikarang, dan Koridor 1. Data uji ini bukan data asli.
- Jam keberangkatan dipakai untuk seluruh perjalanan (tarif pagi Transjakarta dan pengali macet bus).
- Biaya ojek/kendaraan pribadi untuk akses ke halte tidak dihitung dalam tarif.

## Tim

| Peran | Tanggung jawab |
| --- | --- |
| Anggota 1: Data & Backend | Pipeline GTFS/OSM, kerangka FastAPI, endpoint `/lines` dan `/search` |
| Anggota 2: Mesin rute | Graf transit, Dijkstra, fungsi biaya, pengalihan macet, endpoint `/route` |
| Anggota 3: Klien & integrasi | Aplikasi Android, skema API, test integrasi |
