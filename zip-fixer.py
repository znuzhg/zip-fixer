#!/usr/bin/env python3
"""
ZIP FIXER v1
-------------

Gelişmiş ZIP onarım ve kurtarma aracı.

Öne çıkan özellikler:
- ZIP yapısını analiz et (entry listesi, boyutlar, sıkıştırma türü, flag’ler)
- OneDrive / Windows ZIP64 "total_disks = 0" bug fix
- CRC hatalarını görmezden gelerek büyük dosyaları (10GB+) bile mümkün olduğunca çıkar
- Çıkarılan dosyalardan temiz, tekrar oluşturulmuş ZIP üret
- AUTO pipeline: check → ZIP64 fix → best-effort extract → rebuild

Kullanım örnekleri:
    python zip_doctor.py broken.zip --mode auto --out-dir workdir
    python zip_doctor.py broken.zip --mode check
    python zip_doctor.py broken.zip --mode fixzip64
    python zip_doctor.py broken.zip --mode extract --out-dir extracted
    python zip_doctor.py broken.zip --mode rebuild --out-dir extracted --fixed-zip repaired.zip
"""

import argparse
import mmap
import os
import struct
import sys
import traceback
import zipfile
from pathlib import Path
from typing import Optional, List


# ==========================
#  Sabitler
# ==========================

ZIP64_EOCD_LOCATOR_SIG = 0x07064B50  # PK\x06\x07 (little-endian int)
ZIP_LOCAL_HEADER_SIG = 0x04034B50    # PK\x03\x04
ZIP_CENTRAL_DIR_SIG = 0x02014B50     # PK\x01\x02
ZIP_EOCD_SIG = 0x06054B50            # PK\x05\x06


# ==========================
#  Yardımcı Fonksiyonlar
# ==========================

def human_size(num: int) -> str:
    """Boyut formatı (KB, MB, GB, TB...)."""
    n = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} EB"


def log(msg: str) -> None:
    """Ortak log fonksiyonu."""
    print(msg)


# ==========================
#  ZIP Analyzer
# ==========================

class ZipAnalyzer:
    """ZIP dosyasını analiz eder, entry’leri listeler, temel yapısal kontrolleri yapar."""

    def __init__(self, zip_path: Path) -> None:
        self.zip_path = zip_path

    def analyze(self) -> bool:
        log(f"[CHECK] {self.zip_path} inceleniyor...")

        if not self.zip_path.is_file():
            log("[CHECK] Dosya bulunamadı.")
            return False

        try:
            with zipfile.ZipFile(self.zip_path, "r", allowZip64=True) as z:
                infolist = z.infolist()
                log(f"[CHECK] Toplam {len(infolist)} giriş bulundu.")
                for info in infolist:
                    flag = info.flag_bits
                    if info.compress_type == zipfile.ZIP_STORED:
                        comp_type = "STORE"
                    elif info.compress_type == zipfile.ZIP_DEFLATED:
                        comp_type = "DEFLATE"
                    else:
                        comp_type = str(info.compress_type)

                    log(
                        f"  - {info.filename} | {human_size(info.file_size)} "
                        f"(comp: {human_size(info.compress_size)}, "
                        f"type={comp_type}, flags=0x{flag:04x})"
                    )

                log("[CHECK] Merkezi dizin (central directory) okunabildi, arşiv genel olarak yapısal OK.")
                return True

        except Exception as e:
            log(f"[CHECK] HATA: ZipFile ile açılamadı: {e}")
            traceback.print_exc()
            return False


# ==========================
#  ZIP64 Fixer (OneDrive bug)
# ==========================

class Zip64Fixer:
    """
    OneDrive / Windows kaynaklı ZIP64 locator "total_disks = 0" bug’ını düzeltir.
    """

    def __init__(self, zip_path: Path) -> None:
        self.zip_path = zip_path

    def fix_total_disks(self, dry_run: bool = False) -> bool:
        """
        ZIP64 locator içindeki total_disks alanı 0 ise 1 yapar.

        True -> patch uygulandı
        False -> patch uygulanmadı (zaten 1, bulunamadı veya beklenmeyen değer)
        """
        log(f"[ZIP64] {self.zip_path} üzerinde ZIP64 locator kontrolü yapılıyor...")

        if not self.zip_path.is_file():
            log(f"[ZIP64] Dosya bulunamadı: {self.zip_path}")
            return False

        with self.zip_path.open("r+b") as f:
            size = f.seek(0, os.SEEK_END)
            if size < 64:
                log("[ZIP64] Dosya çok küçük, ZIP64 beklenmez.")
                return False

            f.seek(0)
            mm = mmap.mmap(f.fileno(), 0)

            try:
                sig_bytes = struct.pack("<I", ZIP64_EOCD_LOCATOR_SIG)
                pos = mm.rfind(sig_bytes)
                if pos == -1:
                    log("[ZIP64] ZIP64 locator (0x07064b50) bulunamadı.")
                    return False

                log(f"[ZIP64] Locator bulundu: offset {pos}")

                # ZIP64 End of Central Directory Locator:
                # signature   (4 byte)
                # disk_no     (4 byte)
                # eocd_offset (8 byte)
                # total_disks (4 byte)
                if pos + 20 > size:
                    log("[ZIP64] Locator tam değil (dosya sonuna taşıyor).")
                    return False

                raw = mm[pos:pos + 20]
                sig, disk_no, eocd_offset, total_disks = struct.unpack("<IIQI", raw)

                if sig != ZIP64_EOCD_LOCATOR_SIG:
                    log("[ZIP64] Locator signature tutmuyor, işlem iptal.")
                    return False

                log(
                    f"[ZIP64] Mevcut değerler -> "
                    f"disk_no={disk_no}, eocd_offset={eocd_offset}, total_disks={total_disks}"
                )

                if total_disks == 1:
                    log("[ZIP64] 'total_disks' zaten 1, düzeltme gerekmiyor.")
                    return False

                if total_disks != 0:
                    log(
                        f"[ZIP64] 'total_disks' beklenmeyen bir değer: {total_disks}. "
                        f"OneDrive bug’ı olmayabilir."
                    )
                    return False

                log("[ZIP64] OneDrive tarzı bug tespit edildi: total_disks=0. 1 yapacağız.")

                if not dry_run:
                    mm[pos + 16:pos + 20] = struct.pack("<I", 1)
                    mm.flush()
                    log("[ZIP64] total_disks alanı 1 olarak PATCH edildi.")
                else:
                    log("[ZIP64] --dry-run aktif, değişiklik yapılmadı.")

                return not dry_run

            finally:
                mm.close()


# ==========================
#  Best-effort Extractor
# ==========================

class ZipExtractor:
    """
    CRC ve bazı okuma hatalarını görmezden gelerek, mümkün olduğunca fazla dosya çıkarır.
    Büyük dosyalar için bile streaming okuma (chunk’lı).
    """

    def __init__(self, zip_path: Path, out_dir: Path) -> None:
        self.zip_path = zip_path
        self.out_dir = out_dir

    def extract_best_effort(self) -> bool:
        log(f"[EXTRACT] {self.zip_path} -> {self.out_dir}")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        success_any = False

        try:
            with zipfile.ZipFile(self.zip_path, "r", allowZip64=True) as z:
                infolist = z.infolist()
                if not infolist:
                    log("[EXTRACT] Arşivde hiç giriş yok.")
                    return False

                for info in infolist:
                    name = info.filename

                    # Klasör ise sadece oluştur
                    if name.endswith("/"):
                        (self.out_dir / name).mkdir(parents=True, exist_ok=True)
                        continue

                    dest_path = self.out_dir / name
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    log(f"[EXTRACT] → {name}")

                    try:
                        with z.open(info, "r") as src, dest_path.open("wb") as dst:
                            while True:
                                try:
                                    chunk = src.read(1024 * 1024)  # 1MB
                                except Exception as read_err:
                                    # Genelde CRC veya stream sonu ile ilgili hata
                                    log(f"[EXTRACT][WARN] Okuma hatası (CRC vb.): {read_err}")
                                    break

                                if not chunk:
                                    break
                                dst.write(chunk)

                        success_any = True

                    except Exception as e:
                        log(f"[EXTRACT][ERROR] {name} çıkarılamadı: {e}")
                        traceback.print_exc()

            if success_any:
                log("[EXTRACT] En az bir dosya başarıyla çıkarıldı (CRC hataları görmezden gelinmiş olabilir).")
            else:
                log("[EXTRACT] Hiçbir dosya çıkarılamadı.")

            return success_any

        except Exception as e:
            log(f"[EXTRACT] ZipFile açılırken hata: {e}")
            traceback.print_exc()
            return False


# ==========================
#  ZIP Rebuilder
# ==========================

class ZipRebuilder:
    """
    Bir klasör altındaki tüm dosyalardan yeni, temiz bir ZIP oluşturur.
    """

    def __init__(self, src_dir: Path, out_zip: Path, compression: int = zipfile.ZIP_DEFLATED) -> None:
        self.src_dir = src_dir
        self.out_zip = out_zip
        self.compression = compression

    def rebuild(self) -> bool:
        log(f"[REBUILD] {self.src_dir} içinden yeni ZIP oluşturuluyor -> {self.out_zip}")

        if not self.src_dir.is_dir():
            log(f"[REBUILD] Kaynak klasör bulunamadı: {self.src_dir}")
            return False

        self.out_zip.parent.mkdir(parents=True, exist_ok=True)

        file_count = 0
        with zipfile.ZipFile(self.out_zip, "w", compression=self.compression, allowZip64=True) as z:
            for root, dirs, files in os.walk(self.src_dir):
                for fname in files:
                    full_path = Path(root) / fname
                    rel_path = full_path.relative_to(self.src_dir)
                    z.write(full_path, arcname=str(rel_path))
                    file_count += 1
                    log(f"[REBUILD] + {rel_path}")

        log(f"[REBUILD] Tamamlandı. Yeni ZIP: {self.out_zip} (toplam {file_count} dosya)")
        return file_count > 0


# ==========================
#  AUTO Pipeline
# ==========================

def auto_repair_pipeline(zip_path: Path,
                         work_dir: Optional[Path] = None,
                         fixed_zip_path: Optional[Path] = None) -> None:
    """
    AUTO mod:
      1) check
      2) ZIP64 locator fix (varsa)
      3) best-effort extract
      4) rebuild new zip
    """
    log("========== ZIP DOCTOR AUTO MODE ==========")
    log(f"[AUTO] Kaynak ZIP: {zip_path}")

    if work_dir is None:
        work_dir = zip_path.parent / (zip_path.stem + "_work")
    extract_dir = work_dir / "extracted"

    if fixed_zip_path is None:
        fixed_zip_path = work_dir / f"{zip_path.stem}.repacked.zip"

    work_dir.mkdir(parents=True, exist_ok=True)

    # 1) check
    log("\n[AUTO] Adım 1: Yapı kontrolü (check)")
    analyzer = ZipAnalyzer(zip_path)
    analyzer.analyze()

    # 2) ZIP64 fix denemesi
    log("\n[AUTO] Adım 2: ZIP64 locator fix (OneDrive bug tespiti)")
    try:
        fixer = Zip64Fixer(zip_path)
        changed = fixer.fix_total_disks(dry_run=False)
        if changed:
            log("[AUTO] ZIP64 locator başarıyla düzeltildi. (total_disks 0 → 1)")
        else:
            log("[AUTO] ZIP64 düzeltme yapılmadı (gerekli olmayabilir).")
    except Exception as e:
        log(f"[AUTO] ZIP64 fix sırasında hata: {e}")
        traceback.print_exc()

    # 3) CRC’yi görmezden gelerek extract
    log("\n[AUTO] Adım 3: CRC hatalarını görmezden gelerek çıkarma (best-effort)")
    extractor = ZipExtractor(zip_path, extract_dir)
    success_extract = extractor.extract_best_effort()
    if not success_extract:
        log("[AUTO] Uyarı: Extract işlemi başarısız veya eksik oldu.")

    # 4) Yeni ZIP oluşturma
    log("\n[AUTO] Adım 4: Çıkarılan dosyalardan yeni ZIP oluşturma (rebuild)")
    rebuilder = ZipRebuilder(extract_dir, fixed_zip_path)
    success_rebuild = rebuilder.rebuild()
    if success_rebuild:
        log(f"[AUTO] Yeni temiz ZIP: {fixed_zip_path}")
    else:
        log("[AUTO] Yeni ZIP oluşturulamadı (kurtarılan dosya yok olabilir).")

    log("\n[AUTO] İşlem tamamlandı.")
    log("==========================================")


# ==========================
#  CLI
# ==========================

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Gelişmiş ZIP onarım ve kurtarma aracı (OneDrive/ZIP64 + CRC bypass)."
    )
    p.add_argument("zip_file", help="İşlem yapılacak ZIP dosyası")

    mode_group = p.add_argument_group("Mod Seçenekleri")
    mode_group.add_argument(
        "--mode",
        choices=["auto", "check", "fixzip64", "extract", "rebuild"],
        default="auto",
        help="Çalışma modu (varsayılan: auto)",
    )

    p.add_argument(
        "--out-dir",
        help="Extract/çalışma klasörü (yoksa otomatik seçilir)",
    )
    p.add_argument(
        "--fixed-zip",
        help="Rebuild sonrası oluşturulacak yeni ZIP dosya yolu (yoksa otomatik seçilir)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="fixzip64 modunda sadece ne olacağını göster, dosyayı değiştirme",
    )

    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    zip_path = Path(args.zip_file).expanduser().resolve()

    if not zip_path.is_file():
        log(f"[HATA] ZIP dosyası bulunamadı: {zip_path}")
        return 1

    work_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None
    fixed_zip_path = Path(args.fixed_zip).expanduser().resolve() if args.fixed_zip else None

    # AUTO
    if args.mode == "auto":
        auto_repair_pipeline(zip_path, work_dir=work_dir, fixed_zip_path=fixed_zip_path)
        return 0

    # CHECK
    if args.mode == "check":
        analyzer = ZipAnalyzer(zip_path)
        ok = analyzer.analyze()
        return 0 if ok else 1

    # FIXZIP64
    if args.mode == "fixzip64":
        fixer = Zip64Fixer(zip_path)
        changed = fixer.fix_total_disks(dry_run=args.dry_run)
        return 0 if changed else 1

    # EXTRACT
    if args.mode == "extract":
        if work_dir is None:
            work_dir = zip_path.parent / (zip_path.stem + "_extracted")
        extractor = ZipExtractor(zip_path, work_dir)
        ok = extractor.extract_best_effort()
        return 0 if ok else 1

    # REBUILD
    if args.mode == "rebuild":
        if work_dir is None:
            log("[rebuild] --out-dir ile kaynak klasörü belirtmelisin (extract edilmiş dosyalar).")
            return 1
        if fixed_zip_path is None:
            fixed_zip_path = work_dir.parent / (zip_path.stem + ".repacked.zip")
        rebuilder = ZipRebuilder(work_dir, fixed_zip_path)
        ok = rebuilder.rebuild()
        return 0 if ok else 1

    log("[HATA] Bilinmeyen mod.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
