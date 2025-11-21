# 🔧 ZIP FIXER v1

**Gelişmiş ZIP Onarım & Veri Kurtarma Aracı**

ZIP FIXER, bozuk, eksik veya OneDrive/Windows kaynaklı hatalara sahip ZIP dosyalarını onarmak ve mümkün olan en fazla veriyi kurtarmak için geliştirilmiş profesyonel bir araçtır.

---

## ✨ Özellikler

### 🔍 ZIP Analizi

* ZIP içindeki tüm girişleri listeler
* Dosya boyutu, sıkıştırma türü ve flag bilgilerini gösterir
* Merkezi dizin (Central Directory) sağlıklı mı kontrol eder

### 🛠 ZIP64 Onarımı (OneDrive Bug Fix)

Windows / OneDrive kaynaklı yaygın hata:

```
total_disks = 0
```

ZIP FIXER bunu **dosya üzerinde doğrudan binary patch uygulayarak** düzeltir.

### ♻ Best-Effort Extract (CRC Bypass)

* CRC hatalarını görmezden gelerek maksimum dosya kurtarma
* Büyük (10GB+) ZIP dosyalarında bile **1MB chunk** ile stabil okuma
* Bozuk dosyalar bile kurtarılabildiği kadar çıkarılır

### 📦 ZIP Rebuild (Temiz ZIP Üretimi)

Kurtarılan dosyalardan **tamamen yeni ve temiz bir ZIP** oluşturur.

---

## 🚀 Kurulum

Python 3.10+ gerektirir.

```bash
git clone https://github.com/znuzhg/zip-fixer.git
cd zip-fixer
python zip_fixer.py --help
```

Ek bir paket gerektirmez — tamamen Python standart kütüphanesi ile çalışır.

---

## 🧪 Kullanım

### 🔥 1) AUTO Pipeline (Önerilen)

```bash
python zip_fixer.py broken.zip --mode auto --out-dir workdir
```

Sırasıyla şu işlemleri yapar:

* ✔ ZIP analiz
* ✔ ZIP64 fix
* ✔ CRC bypass extraction
* ✔ Temiz ZIP üretimi

---

### 🧾 2) ZIP Yapısını İncele

```bash
python zip_fixer.py broken.zip --mode check
```

---

### 🛠 3) ZIP64 Onarımı

```bash
python zip_fixer.py broken.zip --mode fixzip64
```

Sadece kontrol (dosyayı değiştirmeden):

```bash
python zip_fixer.py broken.zip --mode fixzip64 --dry-run
```

---

### 📤 4) CRC'yi Atlayarak Çıkarma (Best Effort)

```bash
python zip_fixer.py broken.zip --mode extract --out-dir extracted
```

---

### 📦 5) Temiz ZIP Oluşturma (Rebuild)

```bash
python zip_fixer.py broken.zip --mode rebuild --out-dir extracted --fixed-zip repaired.zip
```

---

## 📁 Proje Yapısı

```text
zip_fixer.py        # Ana araç
README.md
examples/           # Test ZIP dosyaları (isteğe bağlı)
```

---

## ⚙ Teknik Detaylar

* `mmap` ile binary patching
* ZIP64 locator taraması
* Streaming extraction (1MB chunk)
* `zipfile` modülü ile güvenli okuma
* Dosya boyut formatı (KB / MB / GB)
* Hata toleranslı extraction yapısı

---

## ⚠ Gelecek Sürümler (Roadmap)

### v2

* 🔒 ZIP Slip güvenlik yaması
* 💣 ZIP Bomb koruması
* 📝 Kısmen kurtarılan dosya raporu

### v3

* 🧬 RAW Recovery Mode
* 📑 Local Header taraması (PK\x03\x04)
* Merkezi dizini tamamen bozuk ZIP’lerde tam kurtarma

---

## 📄 Lisans

MIT License — tamamen özgür kullanım, düzenleme ve dağıtım hakkı sağlar.

---

## 👤 Geliştirici

**👨‍💻 Mahmut Balıkçı (Znuzhg)**
ZIP FIXER v1 — 2025
