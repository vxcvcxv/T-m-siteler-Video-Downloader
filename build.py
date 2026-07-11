import os
import subprocess
import sys

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("Derleme Basliyor...")
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "ALIDWD",
        "videoindirici.py"
    ]
    try:
        subprocess.run(cmd, check=True)
        print("Derleme Tamamlandi. dist/ALIDWD/ icerisinde dosya olusturuldu.")
        print("Lutfen Inno Setup ile 'setup.iss' dosyasini derleyerek kurulum dosyasi (Setup.exe) olusturun.")
    except Exception as e:
        print("Derleme hatasi:", e)

if __name__ == "__main__":
    main()
