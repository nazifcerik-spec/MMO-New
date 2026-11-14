# MP3 Player Tasarım Senaryosu

Kapsam: yazılım uygulaması (masaüstü veya web). Henüz kod yazılmadı.

## 1. Amaç
Kullanıcı yerel MP3 dosyalarını kolayca içe aktarır, düzenler ve çalar. Arayüz sade ve hızlı olur. Çevrimdışı çalışır.

## 2. Hedef Kullanıcılar (Persona)
| Persona | İhtiyaç |
|---|---|
| **Ayşe – Günlük dinleyici** | Klasörü seçip hemen çalmak ister. Karıştırma (shuffle) ve tekrar onun için önemli. |
| **Mehmet – Arşivci** | Binlerce şarkısı var. Etiketlere (ID3) göre arama, sıralama ve çalma listesi ister. |
| **Zeynep – Klavye kullanıcısı** | Uygulamayı fare kullanmadan, kısayollarla ve ekran okuyucuyla kullanmak ister. |

## 3. Ana Kullanım Senaryoları

### S1 – İlk açılış
1. Kullanıcı uygulamayı açar ve "Müzik klasörü ekle" ekranını görür.
2. Bir klasör seçer. Sistem MP3 dosyalarını tarar ve ilerlemeyi gösterir.
3. ID3 etiketleri okunur: sanatçı, albüm, başlık, süre, kapak.
4. Kitaplık ekranı açılır.

### S2 – Şarkı çalma
1. Kullanıcı bir şarkıya çift tıklar.
2. Alt çubukta kapak, başlık, ilerleme çubuğu ve süre görünür.
3. Oynat/Duraklat, Önceki/Sonraki, ses seviyesi ve sessiz düğmeleri kullanılabilir.
4. Şarkı bitince kuyruktaki sonraki şarkı otomatik başlar.

### S3 – Çalma kuyruğu ve modlar
- Karıştırma açılıp kapatılabilir.
- Tekrar modları: kapalı, tümünü tekrarla, tek şarkıyı tekrarla.
- "Sıradakine ekle" ve "Kuyruğun sonuna ekle" seçenekleri bulunur. Kuyruktaki sıra sürükle-bırak ile değiştirilebilir.

### S4 – Çalma listesi
- Kullanıcı yeni bir liste oluşturur, adlandırır ve listeye şarkı ekler, çıkarır ya da sırasını değiştirir.
- Listeler kalıcıdır ve uygulama yeniden açıldığında yerinde durur.

### S5 – Arama ve filtreleme
- Tek bir arama kutusu başlık, sanatçı ve albümde anlık sonuç verir.
- Kitaplık sanatçıya, albüme, süreye veya eklenme tarihine göre sıralanabilir.

### S6 – Kaldığı yerden devam
- Uygulama kapanıp açıldığında son şarkı, konum ve ses seviyesi geri yüklenir.

## 4. Hata ve Kenar Durumları
- Bozuk veya desteklenmeyen dosya atlanır, kullanıcıya uyarı gösterilir ve kuyruk devam eder.
- Dosya taşınmış ya da silinmişse "Dosya bulunamadı" gösterilir ve kaydı kaldırma seçeneği sunulur.
- Etiketi olmayan dosyada dosya adı başlık olarak kullanılır, sanatçı "Bilinmeyen sanatçı" olur.
- Çok büyük kitaplıklarda (10.000+ şarkı) liste sanal kaydırma ile çizilir ve tarama arka planda yapılır.
- Türkçe, Çince gibi özel karakter içeren etiketler doğru gösterilir (UTF-8 / ID3v2 kodlaması).

## 5. Arayüz Yerleşimi (taslak)
```
┌─────────────┬──────────────────────────────────┐
│ Kitaplık    │  [Arama.......................]  │
│ Sanatçılar  │  Başlık     Sanatçı  Albüm  Süre │
│ Albümler    │  ...                             │
│ Listeler +  │                                  │
├─────────────┴──────────────────────────────────┤
│ [Kapak] Şarkı – Sanatçı  ⏮ ⏯ ⏭  ━━●━━ 1:23/3:45 🔀 🔁 🔊 │
└────────────────────────────────────────────────┘
```

## 6. Klavye Kısayolları ve Erişilebilirlik
- `Boşluk`: oynat/duraklat. `←` / `→`: 5 saniye geri/ileri. `Ctrl+←` / `Ctrl+→`: önceki/sonraki şarkı. `↑` / `↓`: ses seviyesi. `Ctrl+F`: arama.
- Tüm düğmelerin erişilebilir etiketi (aria-label) olur, odak göstergesi görünür ve kontrast WCAG AA düzeyindedir.

## 7. Kapsam Dışı (v1)
Akış servisleri, ekolayzer, şarkı sözleri, bulut senkronizasyonu ve etiket düzenleme. Bunlar v2'ye bırakılabilir.

## 8. Kabul Kriterleri
- 1.000 dosyalık klasör 10 saniyenin altında taranır.
- Şarkı geçişinde 300 ms'den uzun sessizlik olmaz.
- Uygulama yeniden başlatıldığında durum korunur.
- Bozuk dosya uygulamayı çökertmez.
- Tüm temel işlemler yalnızca klavyeyle yapılabilir.

## 9. Açık Kararlar
- **Platform:** Electron, web (tarayıcıda klasör erişimi API'si) veya mobil.
- **Veri saklama:** SQLite, IndexedDB veya JSON dosyası.
- **Ses motoru:** HTML5 Audio veya Web Audio API. Kesintisiz (gapless) geçiş isteniyorsa Web Audio API gerekir.
