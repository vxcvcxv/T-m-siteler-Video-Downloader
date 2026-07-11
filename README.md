# ALİDWD - Gelişmiş Medya İndirici & Chrome Eklentisi 🚀

ALİDWD, sosyal medya platformlarından (YouTube, TikTok, Instagram, Twitter) tek tıkla video ve ses (MP3) indirebileceğiniz, kendi Chrome eklentisiyle entegre çalışan, PyQt5 tabanlı modern bir medya yönetim aracıdır.

![ALİDWD Uygulaması](https://img.shields.io/badge/Python-3.x-blue.svg) ![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green.svg) ![yt-dlp](https://img.shields.io/badge/Engine-yt--dlp-red.svg)

## 🌟 Öne Çıkan Özellikler

*   **🌐 Chrome Eklentisi Entegrasyonu:** Tarayıcıda gezinirken her videonun üstünde çıkan akıllı butonlar sayesinde saniyeler içinde indirme başlatın.
*   **⚡ Kısayol Tuşuyla Otomatik İndirme:** Özel olarak atadığınız kısayol tuşuna (Örn: `D`) basarak, fareyi bile kullanmadan o an izlediğiniz videoyu anında indirin! (Instagram Hikayeleri dahil).
*   **📂 Akıllı Klasörleme:** İndirilen videoları aynı klasöre yığmak yerine, sistemi `Platforma Göre` (TikTok, YouTube) veya `Kullanıcıya Göre` (TikTok/@kullanici_adi) otomatik klasörleme yapacak şekilde ayarlayın.
*   **📚 İndirme Geçmişi ve Kütüphane:** SQLite veritabanı sayesinde tüm indirmeleriniz kayıt altında. Uygulama içindeki Kütüphane sekmesinden indirdiğiniz videolara ve klasörlerine anında ulaşın.
*   **🎵 Format ve Kalite:** İster video (MP4) ister sadece ses (MP3) olarak dilediğiniz kalitede indirin.
*   **🎨 Modern ve Dinamik Arayüz:** Karanlık Mod (Dark Mode) destekli, akıcı ve şık arayüz deneyimi.
*   **🌍 Çoklu Dil Desteği:** Türkçe, İngilizce, Almanca, Fransızca, İspanyolca ve daha fazlası!

## ⚙️ Sistem Mimarisi

Uygulama iki ana parçadan oluşur:
1.  **Yerel Sunucu (Python):** `videoindirici.py` dosyası çalıştırıldığında arkaplanda `12090` portundan bir HTTP sunucusu açar. İndirme motorları (`yt-dlp` ve `tikwm`) bu kısımda yer alır.
2.  **Chrome Eklentisi (JavaScript):** Kullanıcı bir videoyu açtığında DOM yapısını analiz eder, butonları sayfaya enjekte eder ve indirme taleplerini yerel sunucuya (`127.0.0.1:12090`) paslar.

## 🛠️ Kurulum

ALİDWD uygulamasını ister hazır paketi indirerek, isterseniz de kaynak koddan çalıştırarak kullanabilirsiniz.

### Seçenek 1: Otomatik Kurulum (Önerilen)
Eğer Python veya komut satırıyla uğraşmak istemiyorsanız, direkt derlenmiş Setup (Kurulum) dosyasını kullanabilirsiniz.
1. Proje içindeki (veya paylaşılan) `ALIDWD_Setup.exe` dosyasını çalıştırın.
2. Kurulum bittikten sonra masaüstünüzdeki ALİDWD kısayoluna çift tıklayarak uygulamayı başlatın.
*(Not: Ayarlar sekmesinden "Bilgisayar açıldığında otomatik başlat" seçeneğini aktif ederseniz, program arka planda her zaman hazır bekler.)*

### Seçenek 2: Kaynak Koddan Çalıştırmak (Geliştiriciler)
Öncelikle gerekli kütüphaneleri kurun:
```bash
pip install PyQt5 yt-dlp
```
Ardından uygulamayı başlatın:
```bash
python videoindirici.py
```

### 3. Chrome Eklentisini Kurmak
1. Google Chrome'da `chrome://extensions/` adresine gidin.
2. Sağ üst köşeden **"Geliştirici Modu"**nu (Developer mode) aktif edin.
3. Sol üstteki **"Paketlenmemiş öğe yükle"** (Load unpacked) butonuna tıklayın.
4. Bu projedeki `extension` klasörünü seçin.

## 📝 Kullanım
Eklenti aktifleştikten ve masaüstü uygulaması çalıştıktan sonra;
*   YouTube'da, TikTok'ta veya Instagram'da gezinirken videoların yanında beliren mor **ALİDWD İndir** butonlarına tıklayabilirsiniz.
*   TikTok profillerinde sağ üstte çıkan **"📂 Profile Bulk"** ile tüm profili indirebilirsiniz.
*   Veya uygulama üzerinden belirlediğiniz "Hızlı İndirme Kısayolu" tuşuna basarak anında işlemi başlatabilirsiniz!

---

*Geliştiriciler için not: Proje, yt-dlp'nin açık kaynaklı altyapısından ve TikTok indirmeleri için anonim api servislerinden beslenmektedir.*
