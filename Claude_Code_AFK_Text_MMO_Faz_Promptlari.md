# OLDSCHOOL AFK TEXT MMORPG - CLAUDE CODE GELİŞTİRME PLANI

Bu doküman, `Oldschool_AFK_Text_MMO_Game_Design.pdf` tasarımını üretilebilir bir yazılım projesine dönüştürmek için Claude Code'a **faz faz verilecek promptları** içerir.

## Nasıl kullanılacak?

1. Tasarım PDF'ini projenin içine `docs/design/Oldschool_AFK_Text_MMO_Game_Design.pdf` adıyla koy.
2. Proje kökünde `CLAUDE.md` ve bu faz planı dosyası bulunsun.
3. Claude Code'a yalnızca başlangıç komutunu ver; ardından ilk tamamlanmamış zorunlu fazdan başlasın.
4. Her faz tamamen uygulanıp testleri yeşile döndüğünde Claude **otomatik olarak sonraki zorunlu faza geçsin**.
5. Fazlar arasında kullanıcı onayı, “devam edeyim mi?” sorusu veya yeni prompt beklenmesin.
6. Her faz sonunda `docs/phase-reports/PHASE_XX.md` kısa raporu ve `.claude/state.json` güncellensin.
7. Bir faz sırasında yeni ve kalıcı bir teknik karar gerekiyorsa `docs/decisions/ADR-XXXX.md` oluşturulsun; küçük ve geri alınabilir kararlar için gereksiz ADR üretilmesin.
8. `CLAUDE.md`, faz planındaki workflow ifadeleriyle çelişirse `CLAUDE.md` üstündür.

---

# PROJE İÇİN SABİT TEKNİK MİMARİ

Bu mimari fazlar boyunca korunmalıdır.

- **Backend:** Python 3.12+ / FastAPI / SQLAlchemy 2 async / Alembic / Pydantic
- **Database:** PostgreSQL
- **Cache / Lock / Rate Limit:** Redis
- **Frontend:** Current stable Next.js App Router + TypeScript
- **UI:** Tailwind CSS + erişilebilir headless component yaklaşımı
- **Data fetching:** TanStack Query
- **Client state:** mümkün olduğunca server state; gerçekten gereken yerlerde hafif local store
- **Static UI localization:** `next-intl` benzeri olgun i18n katmanı
- **Dynamic game localization:** DB tabanlı translation-key sistemi
- **Testing:** pytest + backend integration tests; frontend unit/component tests; Playwright E2E
- **Dev environment:** Docker Compose: postgres + redis + backend + frontend
- **API contract:** OpenAPI; frontend API tipleri otomatik üretilebilir olmalı
- **Time:** bütün server zamanları UTC; UI locale/timezone'a göre gösterir
- **Economy:** para ve ekonomi hesaplarında float kullanma; integer minor unit / exact numeric kullan
- **Game authority:** tüm sonuçlar server authoritative
- **AFK:** 3 saat boyunca gerçek worker loop çalıştırma. Snapshot + deterministic simulation kullan.

## Dört dil

Zorunlu locale'ler:

- `en` - English
- `tr` - Türkçe
- `zh-CN` - 简体中文
- `es` - Español

İngilizce, sistemin canonical/internal dili olsun. Internal slug/id/code'lar İngilizce ve değişmez olsun. Kullanıcıya görünen isimler dört dilde çevrilebilir olsun. Eksik çeviri için fallback sırası: seçili locale -> `en` -> internal safe label.

---

# TASARIMIN DEĞİŞMEZ ÇEKİRDEK KURALLARI

Kod boyunca aşağıdaki oyun tasarımını source-of-truth kabul et:

- Character level cap: **1000**
- Profession level cap: **500**
- Her karakter levelinde: **3 Stat Point**; Lv1000'e kadar 2,997 dağıtılabilir puan
- Statlar: `STR`, `DEX`, `INT`, `VIT`, `WIS`, `SPI`, `LUK`
- Stat soft-cap etkinliği: 0-300 %100, 301-600 %70, 601-900 %45, 901+ %25
- Class breakpoints: **Lv100, Lv300, Lv600, Lv850, Lv1000**
- Lv100: first promotion / iki yol
- Lv300: final specialization / başlangıç classı başına toplam dört specialization
- Lv600: Awakening; yeni class yaratmaz, specialization mekaniğini güçlendirir
- Lv850: Talent capstone
- Lv1000: Class Mastery
- 10 başlangıç classı: **5 Combat + 5 Support**
- 40 final specialization
- 8 race
- 15 priority profession
- Talent: class başına 3 tree, toplam 45 point, tree başına max 25; capstone 25 point + Lv850
- AFK command max: **3 saat**
- Daily recommended full efficiency: ilk 9 saat %100; 9-12 saat %80; 12-18 saat %50; 18-24 saat %25
- Combat launch model: **Passive-first + optional Active Tactics**
- Item tier: **T0-T10**
- Functional launch item target: **1,520+**
- Aynı anda en fazla **3 Specialist Profession License** aktif
- Support solo parity: saf DPS kill speed'inin yaklaşık %70-80'i; sustain daha yüksek
- AFK death: saatlerce ilerlemeyi silme; friction/durability/recovery cost uygula
- Lv1000 sonrası horizontal progression: mastery, titles, collections, professions, relics, seasons

## Level status/title ladder

- Lv1 `Novice`
- Lv100 `Veteran`
- Lv200 `Seasoned`
- Lv300 `Elite`
- Lv400 `Heroic`
- Lv500 `Legendary`
- Lv600 `Champion`
- Lv700 `Mythic`
- Lv800 `Ancient`
- Lv850 `Ascendant`
- Lv900 `Immortal`
- Lv950 `Exalted`
- Lv1000 `Eternal`

## Race list

1. Human - `Adaptable` - race title `Diplomat`
2. High Elf - `Arcane Blood` - `Starborn`
3. Dark Elf - `Night Instinct` - `Umbral`
4. Dwarf - `Stoneborn` - `Deepforged`
5. Orc - `Blood Fury` - `Warborn`
6. Sylvan - `Nature Bond` - `Greenwarden`
7. Beastkin - `Predator Sense` - `Wildblood`
8. Revenant - `Undying Will` - `Deathless`

Racial toplam savaş etkisi zorunlu meta üretmeyecek şekilde yaklaşık %3-5 bandını aşmamalı.

## Class graph

### Warrior
`Warrior -> Guardian / Reaver`
- Guardian -> `Iron Bastion`, `Warlord`
- Reaver -> `Berserker`, `Weapon Master`
Talent: `Defense`, `Arms`, `Blood`

### Rogue
`Rogue -> Assassin / Duelist`
- Assassin -> `Nightblade`, `Venomancer`
- Duelist -> `Blade Dancer`, `Trickster`
Talent: `Assassination`, `Combat`, `Trickery`

### Ranger
`Ranger -> Marksman / Scout`
- Marksman -> `Sharpshooter`, `Arbalist`
- Scout -> `Beastmaster`, `Trapper`
Talent: `Marksmanship`, `Beastcraft`, `Survival`

### Mage
`Mage -> Arcanist / Elementalist`
- Arcanist -> `Runemaster`, `Chronomancer`
- Elementalist -> `Pyromancer`, `Cryomancer`
Talent: `Arcane`, `Element`, `Control`

### Monk
`Monk -> Disciple / Striker`
- Disciple -> `Iron Body`, `Spirit Walker`
- Striker -> `Combo Master`, `Storm Fist`
Talent: `Body`, `Technique`, `Chi`

### Cleric
`Cleric -> Saint / Oracle`
- Saint -> `High Priest`, `Aegis Priest`
- Oracle -> `Prophet`, `Exorcist`
Talent: `Restoration`, `Barrier`, `Faith`

### Paladin
`Paladin -> Warden / Crusader`
- Warden -> `Aegis Knight`, `Lightwarden`
- Crusader -> `Templar`, `Justicar`
Talent: `Aegis`, `Aura`, `Judgment`

### Druid
`Druid -> Grovekeeper / Shapeshifter`
- Grovekeeper -> `Lifebinder`, `Thorn Sage`
- Shapeshifter -> `Bearwarden`, `Mooncaller`
Talent: `Growth`, `Wild`, `Nature`

### Bard
`Bard -> Minstrel / Skald`
- Minstrel -> `Virtuoso`, `Harmonist`
- Skald -> `War Chanter`, `Dirge Singer`
Talent: `Melody`, `Rhythm`, `Discord`

### Shaman
`Shaman -> Totemist / Spiritcaller`
- Totemist -> `Earthwarden`, `Storm Totemist`
- Spiritcaller -> `Ancestor Sage`, `Hexer`
Talent: `Totem`, `Ancestor`, `Element`

## 15 profession

1. Mining
2. Logging
3. Fishing
4. Hunting
5. Herbalism
6. Blacksmithing
7. Weaponsmithing
8. Armorsmithing
9. Leatherworking
10. Tailoring
11. Jewelcrafting
12. Alchemy
13. Cooking
14. Enchanting
15. Engineering

Profession rank breakpoints:
- 1-99 `Apprentice`
- 100-199 `Journeyman`
- 200-299 `Expert` + specialization seçimi
- 300-399 `Artisan`
- 400-499 `Master`
- 500 `Grandmaster`

## Item launch hedefi

- Weapons: 280
- Armor: 360
- Accessories: 120
- Profession Tools: 90
- Consumables: 160
- Materials: 240
- Recipes & Schematics: 120
- Quest / Key / Token: 80
- Cosmetic / Collectible: 70
- Toplam: 1,520

Tier gate:
- T0 Lv1-49
- T1 Lv50-99
- T2 Lv100-199
- T3 Lv200-299
- T4 Lv300-399
- T5 Lv400-499
- T6 Lv500-599
- T7 Lv600-699
- T8 Lv700-849
- T9 Lv850-949
- T10 Lv950-1000

Rarity:
`Common -> Fine -> Rare -> Epic -> Legendary -> Mythic -> Relic`
Starter/tutorial için gerekirse `Worn` ayrı ve düşük değerli başlangıç durumu olarak kullanılabilir; endgame rarity zincirinin parçası değildir.

Class item tags:
`Vanguard`, `Slayer`, `Shadow`, `Hunter`, `Arcane`, `Faith`, `Harmony`, `Primal`, `Spirit`

---

# FAZ 00 - CLAUDE.md, PROJE SÖZLEŞMESİ VE MİMARİ KARARLAR

## Claude Code'a verilecek prompt

> Bu projeyi sıfırdan kuracağız. Önce kod yazmaya başlamadan repository kökünü analiz et. `docs/design/Oldschool_AFK_Text_MMO_Game_Design.pdf` varsa tasarım kaynağı olarak incele. Ardından repository kökünde `CLAUDE.md` oluştur ve aşağıdaki prensipleri kalıcı proje sözleşmesi haline getir.
>
> Amaç: mobil ve masaüstünde çalışan, oldschool text tabanlı, 3 saatlik AFK oturumları olan, server-authoritative MMORPG.
>
> Teknik mimari: FastAPI + SQLAlchemy async + PostgreSQL + Alembic + Redis; frontend Next.js App Router + TypeScript + Tailwind + TanStack Query; Docker Compose; pytest + frontend testleri + Playwright.
>
> Kurallar:
> 1. Game content asla Python/TypeScript condition zincirlerine gömülmesin. Class, race, profession, item, skill, talent, tier, rarity, zone, enemy ve localization mümkün olduğunca data-driven olsun.
> 2. İngilizce internal slug/code'lar immutable olsun. Kullanıcıya görünen tüm metinler `en`, `tr`, `zh-CN`, `es` locale desteğine sahip olsun.
> 3. Backend server-authoritative olacak. Client XP, loot, damage, timer sonucu veya item üretmeyecek.
> 4. AFK oturumu gerçek zamanlı 3 saatlik worker döngüsü değildir. Start anında build snapshot + zone + strategy + seed + start/end kaydedilir. Claim/resolution anında deterministic simulation yapılır. Aynı session iki kez claim edilemez.
> 5. Game engine HTTP katmanından bağımsız, test edilebilir pure-domain servisleri şeklinde tasarlansın.
> 6. Para/XP/material hesaplarında nondeterministic float davranışından kaçın. Uygun yerlerde integer/fixed-point kullan.
> 7. Tüm tarih/saat UTC saklansın.
> 8. DB migration olmadan schema değiştirme.
> 9. Hard delete yalnızca güvenli içerikte; oyuncu/ekonomi/content kayıtlarında soft-delete/versioning/audit tercih et.
> 10. Admin ve game designer işlemleri audit log yazmalı.
> 11. Çeviriler hardcoded UI text olarak dağılmamalı.
> 12. Her faz sonunda lint, type-check, tests ve build çalıştır; başarısız test bırakma.
> 13. Placeholder/TODO ile faz tamamlandı deme. Sonraki faza bırakılan işler açık şekilde phase report'a yazılsın.
> 14. Önce mevcut sistemi oku, sonra minimal ama sağlam değişiklik yap. Çalışan modülü gereksiz yeniden yazma.
> 15. Game balance değerlerini magic number olarak gömme; configuration/content data üzerinden oku.
> 16. Content effect sistemi DB'den ham Python/JS çalıştırmayacak. Güvenli `effect_type + validated params` registry/DSL kullan.
> 17. Her önemli action idempotent olmalı: AFK claim, crafting claim, market purchase, item grant, reward claim.
> 18. Optimistic concurrency/version alanları gereken content ve economy kayıtlarında kullanılmalı.
>
> `docs/architecture/` altında en az şu ADR'leri oluştur:
> - ADR-0001 monorepo ve servis sınırları
> - ADR-0002 deterministic AFK resolution
> - ADR-0003 localization architecture
> - ADR-0004 item template vs item instance
> - ADR-0005 effect registry/DSL
> - ADR-0006 server-authoritative economy
>
> Ayrıca `docs/phase-reports/`, `docs/decisions/`, `docs/game-design/` klasörlerini oluştur. Tasarım PDF'indeki değişmez kuralları kodlanabilir kısa bir `docs/game-design/CANONICAL_RULES.md` dosyasına aktar.
>
> Bu fazda gerçek gameplay geliştirme. Mimariyi, kuralları ve klasör planını hazırla. En sonda `docs/phase-reports/PHASE_00.md` oluştur; yapılanları, kararları ve sonraki faz için riskleri yaz.

### Kabul kriteri
- `CLAUDE.md` var.
- 6 ADR var.
- Canonical rules dokümanı var.
- Henüz gereksiz gameplay kodu yok.

---

# FAZ 01 - MONOREPO, DOCKER, BACKEND/FRONTEND İSKELETİ

## Prompt

> `CLAUDE.md` ve canonical game rules'u oku. FAZ 01'i uygula.
>
> Çalışan bir monorepo oluştur:
> - `/backend`
> - `/frontend`
> - `/docs`
> - `/scripts`
> - `/infra`
>
> Backend FastAPI application factory, config/settings, async SQLAlchemy session, Alembic ve health endpoints kur. PostgreSQL ve Redis bağlantıları health check'te ayrı raporlansın.
>
> Frontend Next.js + TypeScript + Tailwind kur. `/`, `/login`, `/game`, `/admin` route shell'lerini oluştur; admin henüz yalnızca placeholder shell olabilir fakat authorization sonraki fazlarda bağlanacak.
>
> Docker Compose ile postgres, redis, backend, frontend ayağa kalksın. `.env.example` hazırla. Secret'ları repository'ye koyma.
>
> Backend katmanları en az:
> - `api`
> - `domain`
> - `services`
> - `repositories`
> - `models`
> - `schemas`
> - `game_engine`
> - `localization`
>
> Frontend en az:
> - `app`
> - `components`
> - `features`
> - `lib/api`
> - `lib/i18n`
> - `types`
>
> Structured logging, request correlation id ve standart API error envelope ekle.
>
> CI için lint/type/test/build komutlarını tek bir dokümanda tanımla. Basit smoke tests yaz.
>
> Bitirirken bütün servisleri ayağa kaldır ve `/health` ile frontend smoke kontrolünü yap. `PHASE_01.md` üret.

### Kabul kriteri
- Tek komutla dev stack ayağa kalkıyor.
- Backend DB/Redis bağlantısını doğruluyor.
- Frontend backend'e ulaşabiliyor.
- Lint/test/build temiz.

---

# FAZ 02 - LOCALIZATION ÇEKİRDEĞİ: EN/TR/ZH-CN/ES

## Prompt

> FAZ 02: Dört dili mimarinin temeline yerleştir.
>
> Desteklenen locale'ler kesin olarak `en`, `tr`, `zh-CN`, `es`.
>
> İki katmanlı i18n uygula:
> 1. Statik arayüz metinleri frontend locale resource dosyalarında.
> 2. Dinamik oyun içeriği DB'de translation key ile.
>
> DB modelleri tasarla:
> - `localization_keys`
> - `localization_values`
> - locale, key, value, status, updated_by, timestamps, version
> - unique `(key, locale)`
>
> Translation status: `missing`, `draft`, `reviewed`, `published`.
>
> Backend locale resolution:
> - request locale param/cookie/header
> - fallback selected -> `en` -> safe internal label
> - API response'larında kullanıcıya gereken localized value'yu döndür; admin API gerektiğinde tüm locale değerlerini görebilsin.
>
> Frontend header/settings içine language switcher koy. Dil değişince route veya cookie stratejisi tutarlı çalışsın ve seçim persist edilsin.
>
> Çince font/line-breaking ve RTL gerekmiyor ama CJK layout taşmalarını test et. Unicode normalization uygula.
>
> Admin için şimdiden reusable `LocalizedFieldEditor` component'i oluştur: EN/TR/ZH-CN/ES tabları, eksik translation badge, fallback preview.
>
> En az 30 statik UI anahtarını dört dilde seed et: login, logout, character, inventory, level, profession, item, start_afk, claim, settings vb.
>
> Tests: fallback, invalid locale, missing translation, locale switch persistence.
>
> `PHASE_02.md` yaz.

---

# FAZ 03 - AUTH, RBAC, ACCOUNT VE CHARACTER SHELL

## Prompt

> FAZ 03'ü uygula: authentication, authorization ve karakter kabuğu.
>
> Güvenli account modeli oluştur. Browser tabanlı kullanım için secure HttpOnly cookie session veya güvenli access/refresh stratejisi kullan; seçimini ADR ile açıkla. Password hash için güncel güvenli algoritma kullan.
>
> Modeller:
> - User
> - UserSettings
> - Character
> - CharacterSettings
> - Role / Permission
> - AuditLog
>
> RBAC roller:
> - `player`
> - `support_agent`
> - `translator`
> - `item_editor`
> - `game_designer`
> - `admin`
> - `superadmin`
>
> Character başlangıçta name, race_id, base_class_id, level=1, xp=0, unspent_stat_points, progression timestamps içersin. Race/class FK'leri content tablolarına bağlanacak; content seed sonraki fazlarda gelecek.
>
> Character name validation, reserved names, case-insensitive uniqueness policy ve soft deletion oluştur.
>
> Rate limiting ve brute-force koruması ekle.
>
> UI:
> - Login/register
> - Character list
> - Character create wizard shell
> - Logout
> - Admin route guard
>
> Character create henüz race/class seed gelmediyse API'den available content list bekleyecek şekilde tasarlansın; hardcode etme.
>
> Tests ve Playwright auth smoke yaz. `PHASE_03.md` üret.

---

# FAZ 04 - CORE CONTENT ŞEMASI VE CONTENT VERSIONING

## Prompt

> FAZ 04: Oyunun bütün içerik sisteminin ortak omurgasını oluştur.
>
> Amaç: class, race, profession, item, skill, talent, zone gibi içerikler sonradan admin tarafından değiştirilebilsin ve aktif oyuncuların geçmiş session sonuçlarını bozmasın.
>
> Ortak content prensipleri:
> - immutable internal `code/slug`
> - display name/description translation key
> - status: draft/published/disabled/archived
> - content version
> - created_by / updated_by
> - published_at
> - soft delete
> - audit log
> - optimistic concurrency/version check
>
> `ContentRevision`/versioning yaklaşımı tasarla. Yayında kullanılan balance verisinin eski AFK snapshotlarının replay edilmesini sağlayacak kadar izlenebilir olmasını garanti et.
>
> Güvenli effect registry oluştur. Örnek effect type'lar:
> - STAT_FLAT
> - STAT_PERCENT
> - DAMAGE_MULTIPLIER
> - DAMAGE_REDUCTION
> - HEAL_MULTIPLIER
> - SHIELD
> - RESOURCE_GAIN
> - PROC_CHANCE
> - THRESHOLD_TRIGGER
> - EVERY_N_HITS
> - DOT
> - HOT
> - AURA
> - DEBUFF
> - COOLDOWN_MOD
> - LOOT_MODIFIER
> - PROFESSION_YIELD_MOD
>
> Her effect `effect_type + schema_version + validated params JSON` olsun. DB'de arbitrary code/script çalıştırma yok.
>
> API'de published content query ve admin draft query'lerini ayır.
>
> Generic content audit/history viewer için backend endpoint hazırlığı yap.
>
> `PHASE_04.md` üret.

---

# FAZ 05 - STAT, LEVEL, XP, TITLE VE PROGRESSION ENGINE

## Prompt

> FAZ 05: Character progression motorunu üret.
>
> Implement et:
> - Lv1-1000
> - 3 stat point per level
> - STR, DEX, INT, VIT, WIS, SPI, LUK
> - soft-cap effectiveness: 0-300=1.00, 301-600=0.70, 601-900=0.45, 901+=0.25
> - title ladder: Novice, Veteran, Seasoned, Elite, Heroic, Legendary, Champion, Mythic, Ancient, Ascendant, Immortal, Exalted, Eternal
> - breakpoints: 100, 300, 600, 850, 1000
>
> XP curve config-driven olsun. Canonical design toplam yaklaşık 968 saat / 9 saat günlük optimum ile yaklaşık 108 günlük hedefi desteklesin. Exact XP formula'yı `progression_config` üzerinden ayarlanabilir yap; test ortamında hızlı curve kullanılabilsin.
>
> Character derived stats tek merkezi calculator üzerinden hesaplanmalı. `base + race + class + allocated stat + equipment + talent + buff` kaynaklarını ayrı tut ve response'ta breakdown gösterebil.
>
> Auto stat profiles data-driven oluştur:
> - Tank
> - Physical DPS
> - Caster DPS
> - Healer
> - Hybrid Support
>
> Oyuncu manual allocation veya template allocation seçebilsin. Stat respec sistemi için service contract oluştur; Human racial indirimini sonraki race fazına hazır et.
>
> Level-up transaction atomik olsun; çoklu level atlamayı doğru işle; rewards iki kez verilmesin.
>
> API/UI: level progress, unspent points, stat allocation, derived-stat breakdown, next breakpoint.
>
> Tests: soft caps, lv1000 hard cap, multi-level gain, idempotent reward, invalid allocation.
>
> `PHASE_05.md` üret.

---

# FAZ 06 - RACE SİSTEMİ VE 8 IRK

## Prompt

> FAZ 06: Race content modelini ve sekiz launch race'i seed et. Hiçbir race class kilitlemesin.
>
> Race'ler:
> - Human / Adaptable / Diplomat
> - High Elf / Arcane Blood / Starborn
> - Dark Elf / Night Instinct / Umbral
> - Dwarf / Stoneborn / Deepforged
> - Orc / Blood Fury / Warborn
> - Sylvan / Nature Bond / Greenwarden
> - Beastkin / Predator Sense / Wildblood
> - Revenant / Undying Will / Deathless
>
> Canonical etkileri design PDF'den data olarak oluştur; örneğin Human XP +3%, Dwarf VIT/block/mining, Orc STR ve low-HP damage, Sylvan WIS/HoT/herbalism/fishing vb. Effect registry kullan; race için if/else yazma.
>
> Racial toplam savaş avantajlarının yaklaşık %3-5 üst sınırını aşmamasını kontrol eden `balance validator` yaz. Bu validator admin publish aşamasında warning/error üretebilsin.
>
> Character creation wizard'a localized race cards ekle. Her kartta trait, race title, doğal uyum açıklaması ve sayısal etkiler gösterilsin; “recommended” sadece bilgi olsun, class kilidi olmasın.
>
> Racial effect breakdown derived stats ekranında görülebilsin.
>
> Dört locale için seed çevirilerini oluştur.
>
> `PHASE_06.md` üret.

---

# FAZ 07 - CLASS, PROMOTION VE 40 SPECIALIZATION

## Prompt

> FAZ 07: 10 base class, Lv100 promotion ve Lv300 specialization sistemini data-driven kur.
>
> Base classlar:
> Warrior, Rogue, Ranger, Mage, Monk, Cleric, Paladin, Druid, Bard, Shaman.
>
> Canonical class graph'ı `CANONICAL_RULES.md` ve design PDF'den birebir uygula. Sonuç tam olarak 40 Lv300 specialization olmalı.
>
> Modeller:
> - BaseClass
> - ClassBranch / PromotionPath
> - Specialization
> - ClassProgressionRequirement
> - CharacterClassProgression
> - ClassResourceDefinition
> - AllowedWeaponFamily
> - ArmorProficiency
>
> Lv100 promotion ancak level>=100 ve prerequisite sağlandığında seçilsin. Lv300 specialization yalnızca seçilmiş Lv100 branch altında geçerli olsun. Lv600 Awakening, Lv850 capstone, Lv1000 mastery state alanlarını modelle fakat skill/talent implementasyonu sonraki fazda.
>
> Class resource'ları data-driven tanımla: Rage, Energy/Opportunity, Focus, Mana/Arcane Charge, Chi, Faith, Conviction, Nature Essence, Rhythm, Spirit Charges.
>
> Support sınıfları için ortak `Solo Accord`/solo conversion kontratını oluştur: party dışında support power'ın configurable kısmı saldırı/spell gücüne dönüşebilsin. Default canonical değer %35 olsun.
>
> UI:
> - class create selection
> - promotion modal/page
> - specialization tree visualization
> - locked/unlocked breakpoint gösterimi
> - respec policy placeholder değil, config/service olarak gerçek uygulanabilir kontrat
>
> 10 class ve 40 specialization için dört dilde isim/açıklama seed et. English canonical name değişmez.
>
> Tests: invalid branch selection, early promotion, duplicate promotion, specialization count exactly 40.
>
> `PHASE_07.md` üret.

---

# FAZ 08 - SKILL, PASSIVE, TALENT VE AWAKENING MOTORU

## Prompt

> FAZ 08: Ability sistemini kur. Hem aktif skill hem passive-only combat aynı ability/effect altyapısını kullanabilmeli.
>
> Modeller:
> - AbilityDefinition
> - AbilityRank
> - AbilityEffect
> - PassiveTrigger
> - TalentTree
> - TalentNode
> - TalentEdge/prerequisite
> - CharacterTalentAllocation
> - AwakeningDefinition
> - MasteryDefinition
>
> Ability türleri: `ACTIVE`, `PASSIVE`, `ULTIMATE`, `STANCE`, `AURA`, `PROC`.
>
> Aktif ability alanları: resource cost, cooldown, target rule, cast time gerekiyorsa, effect list, tags.
>
> Passive trigger örnekleri: on_hit, on_crit, on_block, on_dodge, on_heal, hp_below, resource_above, every_n_hits, on_kill, combat_start, target_debuff_count.
>
> Talent sistemi:
> - class başına 3 tree
> - toplam 45 point
> - tree max 25
> - capstone: tree 25 + Lv850
> - aynı anda iki capstone mümkün olmamalı
>
> Canonical talent tree adlarını seed et:
> Warrior Defense/Arms/Blood; Rogue Assassination/Combat/Trickery; Ranger Marksmanship/Beastcraft/Survival; Mage Arcane/Element/Control; Monk Body/Technique/Chi; Cleric Restoration/Barrier/Faith; Paladin Aegis/Aura/Judgment; Druid Growth/Wild/Nature; Bard Melody/Rhythm/Discord; Shaman Totem/Ancestor/Element.
>
> Her class için PDF'deki core skill/passive setini başlangıç seed'i olarak aktar. Launch'ta specialization başına maksimum 5 temel active + 1 ultimate sınırını enforce eden validator oluştur; passive sayısı için ayrı limit configurable olsun.
>
> Lv600 Awakening etkilerini effect registry ile tanımla; kod içinde specialization-name if/else kullanma.
>
> Talent reset: Lv300'e kadar düşük/ücretsiz; 300-600 orta maliyet; 600+ gold+nadir material olacak şekilde config/service kur.
>
> Admin publish validation: circular talent dependency, unreachable node, invalid effect params, duplicate capstone gibi hataları engelle.
>
> Tests + tree graph tests oluştur. `PHASE_08.md` üret.

---

# FAZ 09 - COMBAT ENGINE CORE

## Prompt

> FAZ 09: HTTP'den bağımsız deterministic combat engine yaz.
>
> Girdi:
> - CharacterCombatSnapshot
> - Enemy/EncounterSnapshot
> - CombatStrategy
> - deterministic seed
> - content version ids
>
> Çıktı:
> - win/loss/death
> - elapsed simulated time
> - damage dealt/taken
> - healing/shield
> - resource usage
> - consumables
> - proc counts
> - XP/loot eligibility hooks
> - compact combat log events
>
> Combat math modülleri:
> - attack interval
> - hit/accuracy
> - crit
> - armor/resistance mitigation
> - block/dodge
> - physical/magic/true damage support
> - DOT/HOT
> - shields
> - buffs/debuffs
> - threat hooks
> - death
>
> Damage formula config-driven ve testlenebilir olsun. PvE ve ileride PvP coefficient katmanı ayrılabilsin.
>
> Event scheduler her milisaniyeyi loop etmesin; next-event stepping yaklaşımı kullan. Seed aynıysa snapshot aynı sonuç vermeli.
>
> Combat log localization'dan bağımsız structured event olsun: örn `{event_type:'CRIT', actor_id, target_id, ability_code, amount}`. UI sonradan locale metnine dönüştürsün.
>
> Performance benchmark yaz: yüzlerce tipik encounter simulation kısa sürede hesaplanabilsin.
>
> Golden deterministic tests oluştur.
>
> `PHASE_09.md` üret.

---

# FAZ 10 - PASSIVE-ONLY COMBAT SENARYOSU

## Prompt

> FAZ 10: Ana launch combat modeli olan Passive-Only motorunu tamamla.
>
> Oyuncu aktif buton spamlamaz; şu stratejileri seçer:
> - Stance: Aggressive / Guarded / Efficient
> - Target Priority
> - Potion Threshold
> - Risk Level
> - Loot Filter
> - class passive profile
>
> Passive motor katmanları:
> - Base Attack
> - Stance
> - Trigger Passive
> - Threshold Passive
> - Cycle Passive
> - Target Rule
> - Consumable Rule
>
> Class identity mapping'i implement et:
> - Warrior: block counter, execute threshold, rage stack, weapon cycle
> - Rogue: opportunity stack, poison proc, dodge counter, every-N-hit finisher
> - Ranger: aim stack, trap proc, pet auto-command
> - Mage: element cycle, rune sequence, mana threshold, spell echo
> - Monk: chi cycle, combo pattern, defensive threshold
> - Cleric: auto-heal threshold, shield refresh, cleanse priority
> - Paladin: aura, block shield, judgment proc
> - Druid: HoT refresh, form threshold, thorn trigger
> - Bard: party-condition song rotation
> - Shaman: totem slot priority, spirit proc
>
> Bunları class-name hardcode ederek değil ability/passive data ve strategy resolver üzerinden çalıştır.
>
> UI'da basit ve gelişmiş AFK profile editor oluştur. Kullanıcı hazır preset seçebilsin ve isterse detay açabilsin.
>
> Tests: threshold ordering, deterministic proc, consumable limit, support solo behavior.
>
> `PHASE_10.md` üret.

---

# FAZ 11 - OPTIONAL ACTIVE TACTICS SENARYOSU

## Prompt

> FAZ 11: Passive-first çekirdeği bozmadan optional Active Tactics katmanını ekle.
>
> Amaç manuel skill spam değil; oyuncu 1-6 priority rule tanımlar.
>
> Canonical örnek priority:
> 1. HP <35% -> defensive/heal
> 2. Boss -> single-target finisher
> 3. enemy_count >=3 -> AoE
> 4. resource >70% -> spender
> 5. cooldown ready -> buff/debuff
> 6. fallback basic attack
>
> Rule editor güvenli DSL kullansın; arbitrary expression/code çalıştırma yok. Condition registry tanımla: HP_PERCENT, RESOURCE_PERCENT, TARGET_TYPE, ENEMY_COUNT, TARGET_HP, BUFF_PRESENT, DEBUFF_PRESENT, COOLDOWN_READY vb.
>
> Specialization başına maximum 5 core active + 1 ultimate validator'ı burada kullan.
>
> Game mode/config ile `PASSIVE_ONLY`, `ACTIVE_TACTICS`, `HYBRID` seçilebilir olsun. Launch default HYBRID fakat ordinary AFK Passive-first çalışsın.
>
> Boss/arena gibi encounter'lar Active Tactics'e ek karar alanı sağlayabilsin ama oyuncuyu her birkaç saniyede bir input vermeye zorlamasın.
>
> Priority rule simulator/preview UI ekle: sample encounter üzerinde hangi rule'un kaç kez çalışacağını göster.
>
> Tests ve E2E priority editor testi yaz. `PHASE_11.md` üret.

---

# FAZ 12 - ZONE, ENEMY, ENCOUNTER, BOSS VE DROP SOURCE

## Prompt

> FAZ 12: PvE content modelini oluştur.
>
> Modeller:
> - Zone
> - ZoneTier
> - EnemyTemplate
> - EnemyAbilityProfile
> - EncounterTemplate
> - BossTemplate
> - DropTable
> - DropTableEntry
> - Spawn/encounter weight
> - ZoneRequirement
>
> Zone'larda recommended/min level, danger rating, profession nodes, enemy pool, boss pool, loot modifiers, environment tags ve localization olsun.
>
> Risk profilleri:
> - Safe: %85 XP/Loot, çok düşük ölüm
> - Balanced: %100, orta
> - Dangerous: %120, yüksek
> - Elite Hunt: %135 + rare chance, çok yüksek
>
> Risk profili numeric config olarak saklansın.
>
> Enemy stat scaling ve zone tier scaling ayrı config olsun. Bosslar normal AFK encounter'dan ayırt edilsin.
>
> İlk geliştirme/test için her tier'e küçük sample zone/enemy seti seed et; 1000 level boyunca final content'i bu fazda elle yazmak zorunda değilsin.
>
> Admin publish validator: erişilemeyen zone, boş encounter pool, invalid level range, circular prerequisite, impossible enemy stats warning.
>
> `PHASE_12.md` üret.

---

# FAZ 13 - 3 SAATLİK AFK SESSION ENGINE

## Prompt

> FAZ 13: Oyunun kalbi olan AFK session sistemini production-grade uygula.
>
> Session başlangıcında şunları immutable snapshot olarak kaydet:
> - character level/xp
> - effective stats
> - race effects
> - class/specialization/awakening/talents
> - equipment item instance stats/effects
> - consumable policy + available quantity snapshot/hold strategy
> - zone
> - risk mode
> - passive/active tactics profile
> - profession task varsa task
> - content version references
> - deterministic server seed
> - started_at / ends_at; max 3h
>
> Oyuncu session devam ederken equipment/talent değiştirirse mevcut session sonucu etkilenmesin.
>
> Real-time 3h loop oluşturma. Resolve service elapsed period'i deterministic olarak simüle etsin. Expired session background sweeper ile önceden resolve edilebilir ama claim anında da güvenli resolve edilebilsin.
>
> Claim transaction:
> - distributed lock/idempotency key
> - yalnızca bir kez reward
> - inventory capacity politikası
> - XP, profession XP, item/material, durability, death/recovery
> - audit/economy ledger
>
> Daily efficiency curve UTC/player-day policy ile doğru hesaplanmalı: 0-9h 100%, 9-12h 80%, 12-18h 50%, 18-24h 25%. Session birden fazla banda taşarsa süreyi dilimleyerek hesapla.
>
> “3-Hour Satisfaction Rule”: sonuçta görünür progression sinyali üreten summary sistemi ekle: XP%, material milestone, pity progress, profession progress vb.
>
> Rested bonus için extension point oluştur; exploit yaratmayacak şekilde config kapalı başlayabilir.
>
> UI: start AFK, countdown, current snapshot summary, claim screen, localized battle/farm summary.
>
> Tests: 3h cap, duplicate claim, concurrent claim, mid-session build change, daily band crossing, deterministic replay.
>
> `PHASE_13.md` üret.

---

# FAZ 14 - ITEM DOMAIN MODELİ

## Prompt

> FAZ 14: Item sistemini template ve instance olarak ayırarak kur.
>
> `ItemTemplate` içerik tanımıdır; `ItemInstance` oyuncuya ait gerçek kopyadır.
>
> ItemTemplate alanları en az:
> - internal code/slug
> - localized name/short description/lore keys
> - category, subcategory, family
> - equipment slot
> - weapon family / armor family
> - tier T0-T10
> - min character level
> - rarity
> - stack size
> - bind policy
> - tradeable/sellable flags
> - base vendor value
> - durability config
> - socket config
> - class tags
> - allowed/blocked classes optional
> - allowed/blocked races optional
> - stat requirements
> - profession requirement optional
> - base stat grants
> - fixed effects
> - affix pool rules
> - unique effect
> - set id optional
> - salvage/disenchant outputs
> - icon asset reference
> - source metadata
> - content version/status
>
> ItemInstance alanları:
> - owner
> - template + template version
> - rolled affixes
> - rolled values
> - durability
> - sockets/gems
> - binding state
> - quality/upgrade state
> - created/source timestamps
> - provenance id
>
> Rarity ve affix budget canonical kuralları:
> Common 0-1, Fine 1-2, Rare 2-3, Epic 3-4, Legendary 4-5 + unique effect, Mythic 5-6 + unique/mastery scaling, Relic fixed build-changing.
>
> Tier level gates T0-T10 canonical aralıklarla seed edilsin.
>
> Item stat requirement validator oluştur. Ortalama o levelde dağıtılabilir stat bütçesinin yaklaşık %60-70 üstünü zorunlu kılacak requirement publish edilirken warning/error versin.
>
> Support heavy/caster/finesse/healing item requirement profiles config olsun.
>
> Item roll deterministic seed ile üretilebilsin ve provenance loglansın.
>
> `PHASE_14.md` üret.

---

# FAZ 15 - ADMIN ITEM STUDIO: DETAYLI ARAYÜZ

## Prompt

> FAZ 15: Profesyonel bir `/admin/items` Item Studio geliştir. Bu ekran ileride 1,520+ item'i kod değiştirmeden yönetebilmemi sağlamalı.
>
> Yetki:
> - item_editor: create/edit draft
> - translator: localization edit
> - game_designer: balance/publish
> - admin/superadmin: full
>
> ## Ana yerleşim
> Desktop'ta üç ana alan kullan:
> 1. Sol: filtreler ve item tree/category
> 2. Orta: virtualized item table/grid
> 3. Sağ: seçili item quick inspector
>
> Item açıldığında full editor route/drawer aşağıdaki tablarla çalışsın:
>
> ### 1. General
> code, category, subcategory, family, slot, tier, min level, rarity, status, icon, tags.
>
> ### 2. Localization
> EN / TR / ZH-CN / ES sekmeleri.
> Name, short description, full description/lore.
> Translation status badge, missing field warning, English fallback preview.
>
> ### 3. Requirements
> STR/DEX/INT/VIT/WIS/SPI/LUK requirement builder; class/race/profession restrictions; level/tier gates.
> Publish öncesi %60-70 stat-budget validator sonucu görünsün.
>
> ### 4. Stats & Effects
> base stat rows; effect registry dropdown; parameter form schema'ya göre otomatik oluşsun.
> Ham JSON sadece advanced read/validated edit modunda; arbitrary script yok.
>
> ### 5. Affixes
> allowed affix pools, rarity budget, min/max rolls, weights, exclusive groups, class tags.
>
> ### 6. Unique / Set
> unique effect, set membership, 2/3/4/... piece effects.
>
> ### 7. Sockets / Upgrade
> socket count/type, upgrade curve, repair/durability.
>
> ### 8. Sources
> drop tables, zones, bosses, recipes, vendors, quests, events. Reverse references göster.
>
> ### 9. Craft / Salvage
> crafting profession, recipe, ingredients, output quality; salvage/disenchant tables.
>
> ### 10. Preview
> Dört dil görünümü; item tooltip preview; tier/rarity appearance; sample character equip delta.
> “Preview on Warrior Lv600”, “Mage Lv850” gibi test character profile seçilebilsin.
>
> ### 11. History
> audit log, version diff, author, publish time, rollback-to-new-revision.
>
> ## Liste özellikleri
> Search internal code + localized name; filters category/tier/rarity/slot/family/tag/class/profession/status/translation completeness; sortable columns; pagination/virtualization; saved filters.
>
> ## İşlemler
> - Create
> - Clone
> - New version
> - Archive
> - Compare
> - Bulk edit safe fields
> - Bulk localization status
> - CSV/JSON export
> - CSV/JSON import with dry-run
> - Download validation report
>
> ## Item Generator Wizard
> Çok önemli: 1,520 item'i tek tek girmek zorunda kalmayayım.
> Wizard parametreleri:
> - category/family
> - tier range
> - rarity distribution
> - stat profile
> - naming pattern/translation key pattern
> - affix pool
> - count
> - class tag
> - material theme
>
> Önce dry-run tablo üret; hiçbir şeyi DB'ye yazma. Validation + duplicate code check çalıştır ve sonucu audit log/rapora kaydet. Validation başarılıysa ve işlem yalnızca development/local content verisini etkiliyorsa kullanıcı onayı beklemeden atomic batch create yap. Üretim verisi veya geri alınamaz harici işlem söz konusuysa `CLAUDE.md` güvenlik kurallarını uygula.
>
> ## UX
> Unsaved changes guard; keyboard shortcuts; success/error toast; destructive confirmation; accessible forms; responsive tablet görünümü.
>
> ## API
> Admin endpoints oyuncu public content endpoints'ten ayrı olsun. Filtering server-side. Optimistic concurrency zorunlu; version conflict durumunda diff göster.
>
> ## Test
> RBAC, create/edit/publish, concurrent edit conflict, translation fallback, invalid effect schema, bulk import dry-run, clone, archive, rollback, generator duplicate prevention için testler yaz.
>
> `docs/admin/ITEM_STUDIO.md` içinde ekran mimarisini ve alan şemasını dokümante et. `PHASE_15.md` üret.

---

# FAZ 16 - INVENTORY, EQUIPMENT, TOOLTIP VE ITEM REQUIREMENT

## Prompt

> FAZ 16: Player inventory/equipment akışını tamamla.
>
> Inventory modelinde stackable ve unique instances doğru desteklensin. Equipment slotları data-driven tanımlansın. Equip işlemi atomik ve server-authoritative olsun.
>
> Equip validation:
> - min level
> - stat requirements
> - class/race restrictions
> - weapon proficiency
> - slot compatibility
> - binding
>
> Requirement hesabında itemin kendi verdiği statın itemi equip etmeyi kendi kendine mümkün kılması gibi circular exploitleri önle: requirement pre-equip stats üzerinden doğrulansın.
>
> Derived stat calculator equip/unequip sonrası tek source of truth olsun.
>
> Inventory overflow politikası: AFK claim sırasında reward mail/stash/overflow container gibi güvenli mekanizma tasarla; reward kaybolmasın ve sınırsız exploit yaratmasın.
>
> Item tooltip dört dilde, stat delta, requirement, source, rarity, tier, affix, unique effect, bind, durability ve marketability göstersin.
>
> Loot filter sistemi category/rarity/tier/tag bazında tanımlanabilir olsun; “auto salvage” daha sonra açılabilir, şimdiden contract oluştur.
>
> `PHASE_16.md` üret.

---

# FAZ 17 - PROFESSION PROGRESSION VE 15 MESLEK

## Prompt

> FAZ 17: 15 profession'ı data-driven kur.
>
> Ranklar: Apprentice 1-99, Journeyman 100-199, Expert 200-299, Artisan 300-399, Master 400-499, Grandmaster 500.
>
> Lv200'de her profession iki specialization seçeneğine sahip olsun:
> - Mining: Prospector / Deep Miner
> - Logging: Forester / Resin Harvester
> - Fishing: Angler / Pearl Diver
> - Hunting: Tracker / Trophy Hunter
> - Herbalism: Botanist / Seedkeeper
> - Blacksmithing: Refiner / Master Forger
> - Weaponsmithing: Edge Master / Impact Smith
> - Armorsmithing: Bulwark Smith / Plate Artisan
> - Leatherworking: Tanner / Hide Artisan
> - Tailoring: Weaver / Mystic Tailor
> - Jewelcrafting: Gemcutter / Runesetter
> - Alchemy: Elixirist / Toxicologist
> - Cooking: Provisioner / Feastmaster
> - Enchanting: Imbuer / Disenchanter
> - Engineering: Mechanist / Trapwright
>
> Aynı anda yalnızca 3 Specialist License aktif olabilir. License değiştirme cooldown + economy cost config olsun.
>
> Profession XP character XP'den bağımsız. Tool tier, zone requirement, relevant stat, recipe knowledge ve quality mekaniklerini uygula.
>
> Relevant stats canonical tasarımdan seed edilsin: Mining STR/VIT, Fishing DEX/LUK, Herbalism WIS/LUK, Enchanting INT/SPI vb.
>
> Profession effectleri character combat code'una gömülmesin; profession service/effect registry kullan.
>
> Profession title sistemini seed et: Grandmaster Miner, Grandmaster Blacksmith vb.
>
> `PHASE_17.md` üret.

---

# FAZ 18 - GATHERING, CRAFTING, RECIPE, QUALITY VE ENCHANTING

## Prompt

> FAZ 18: Meslekleri gerçek oynanış döngüsüne bağla.
>
> Gathering:
> - zone node/table
> - tool tier
> - profession level
> - yield
> - rare find
> - AFK efficiency
> - specialization bonuses
>
> Crafting:
> - RecipeDefinition
> - ingredients
> - tool/workstation requirement
> - profession level
> - craft time
> - quality chance
> - output template/instance
> - failure/partial return policy
> - batch crafting
>
> Quality zinciri: Common -> Fine -> Superior -> Masterwork -> Mythic Crafted. Bu crafting quality'yi item rarity ile karıştırma; iki ayrı kavram ve UI label olsun.
>
> Rare/Epic recipes drop/reputation/exploration kaynağına bağlanabilsin.
>
> Enchanting için safe reroll/imbue sistemi; gold/material sink ve deterministic audit ledger oluştur.
>
> Engineering AFK utility gadget'ları combat/economy sınırları içinde effect registry ile çalışsın.
>
> Craft claim idempotent olsun. Material reservation/consumption transaction safe olsun.
>
> UI: profession dashboard, rank progress, recipes, craft queue, gathering setup, specialist license panel.
>
> `PHASE_18.md` üret.

---

# FAZ 19 - LOOT, PITY, DROP TABLE VE 1,520 ITEM CATALOG GENERATOR

## Prompt

> FAZ 19: Loot ve launch item catalog üretim sistemini kur.
>
> DropTable weighted entries; rarity modifiers; LUK etkisi; zone/boss/tag koşulları; profession material drop'ları; unique/relic limitleri desteklensin.
>
> LUK loot etkisi küçük ve diminishing-return olsun; pay-to-win benzeri aşırı fark yaratma.
>
> Pity sistemi ayrı configurable mechanic olsun. Rare unique drop için user-visible progress gerekiyorsa yalnızca uygun içerikte göster.
>
> Admin Item Studio generator'ını kullanarak dry-run ile tam launch hedefini üret:
> - 280 Weapons
> - 360 Armor
> - 120 Accessories
> - 90 Profession Tools
> - 160 Consumables
> - 240 Materials
> - 120 Recipes & Schematics
> - 80 Quest/Key/Token
> - 70 Cosmetic/Collectible
>
> Toplam tam olarak 1,520 seed template hedefle; unique curated items ayrıca bu sayı içinde planlanabilir. Generator sonucu `docs/content/ITEM_CATALOG_REPORT.md` üret: tier, rarity, category, class-tag dağılımı.
>
> İsimleri aynı kalıp tekrarından kaçınacak naming token sistemiyle üret. English canonical name oluştur; TR/ZH-CN/ES için ilk seed çevirilerini otomatik üretirken status `draft` yap. English `published/reviewed` olabilir. Çeviri kalite kontrolü admin'de kalmalı.
>
> Stat budget validator ile tier başına outlier raporu üret.
>
> `PHASE_19.md` üret.

---

# FAZ 20 - ECONOMY: GOLD, VENDOR, REPAIR, TRADE VE MARKET

## Prompt

> FAZ 20: Ekonomiyi server-authoritative ledger mantığıyla kur.
>
> Economy ledger her gold/material kritik hareketinde source/sink ve correlation id kaydetsin.
>
> Gold sinks canonical tasarıma uygun:
> - repair
> - respec
> - specialist license swap
> - crafting quality attempts
> - enchant reroll
> - prestige/cosmetic
>
> Vendor buy/sell ve dynamic olmayan temel fiyat sistemini oluştur.
>
> Player-to-player market ekle:
> - listing
> - buyout
> - market tax
> - expiration
> - cancel
> - bind/non-tradeable validation
> - atomic purchase
> - race condition protection
>
> İlk sürümde gerçek zamanlı auction bid şart değil; buyout market daha güvenli ve basit. Auction daha sonra extension point olabilir.
>
> Price overflow, negative value, duplication, concurrent buy exploitlerine test yaz.
>
> Admin economy dashboard için gold sources/sinks, item creation/destruction ve market volume aggregation endpointleri hazırla.
>
> `PHASE_20.md` üret.

---

# FAZ 21 - PARTY, SUPPORT ROLLERİ VE GROUP AFK

## Prompt

> FAZ 21: Support sınıflarının anlamlı olacağı party sistemini kur.
>
> Default party size 5 olsun; config ile değişebilir.
>
> Party:
> - invite/accept/leave/kick/leader
> - role preference
> - online/AFK state
> - party chat için minimal contract
>
> Group AFK session tasarla. Party leader encounter/zone seçsin; her karakter kendi snapshot'ına sahip olsun. Reward personal loot veya açıkça tanımlı shared rule ile exploit-free dağıtılsın.
>
> Support contribution metriği sadece raw damage olmasın: healing, shield, buff uptime, debuff contribution, damage prevented, party DPS gained ölçülebilsin.
>
> Solo Accord party'de otomatik kapanmalı; party join/leave sırasında devam eden AFK snapshot değişmemeli.
>
> Party composition bonusları aşırı meta yaratmayacak şekilde config-driven olsun.
>
> Combat engine threat/healing/aura hooks burada group encounter'a bağlansın.
>
> `PHASE_21.md` üret.

---

# FAZ 22 - QUEST, PROMOTION CHALLENGE, TITLE, ACHIEVEMENT VE PRESTIGE

## Prompt

> FAZ 22: Uzun vadeli hedef sistemlerini kur.
>
> Quest modelini graph/prerequisite destekli data-driven oluştur. Quest types: kill, collect, profession, explore, boss, promotion, tutorial.
>
> Lv100 ve Lv300 seçimleri için istenirse kısa promotion challenge/quest bağlanabilsin; level tek başına sufficient veya quest required config ile ayarlanabilir.
>
> Title/status sistemi:
> - level title
> - class title
> - race epithet
> - profession title
> - achievement title
> - guild rank extension
>
> Warrior örneği gibi class title dönüşüm mantığını generic yap: Base -> Branch -> Specialization -> Awakened -> Ascendant -> Eternal.
>
> Status rarity: Bronze, Silver, Gold, Platinum, Mythic, Relic. Bunlar power rarity değil prestige presentation olsun.
>
> Achievement engine counters/events üzerinden çalışsın; her combat event'i DB'ye spamlamadan aggregation yap.
>
> Collection ve title seçme UI oluştur.
>
> `PHASE_22.md` üret.

---

# FAZ 23 - PLAYER UI / TEXT MMO EXPERIENCE / PWA

## Prompt

> FAZ 23: Oyunun asıl kullanıcı deneyimini tamamla. Hedef: mobilde çok rahat, masaüstünde bilgi zengin, oldschool text MMO hissi.
>
> Main game shell:
> - top: character identity, level/xp, main resources
> - left/desktop nav: Character, Adventure, AFK, Inventory, Equipment, Skills/Talents, Professions, Crafting, Market, Party, Collections, Settings
> - center: current context
> - right desktop: activity log / notifications / current AFK summary
> - mobile bottom navigation + drawers
>
> Text combat/activity log okunabilir olsun; structured events localized cümlelere çevrilsin. Crit, block, proc, loot ve level-up görsel hiyerarşiyle ayrılsın fakat ekranı spamlamasın. Summary-first, details-expand yaklaşımı kullan.
>
> AFK start ekranında zone, risk, stance, target priority, potion threshold, loot filter, passive profile/active tactics profile ve süre (max 3h) seçimi olsun.
>
> “Next meaningful goal” kartı ekle: next level title, promotion, talent point, profession rank, item tier veya zone unlock.
>
> PWA installable olsun. Offline modda gameplay sonucu üretme; sadece cached read-only ekranlar ve bağlantı durumu göster. Server authoritative kuralı korunacak.
>
> EN/TR/ZH-CN/ES bütün temel ekranlarda tamamlanmış olsun. CJK layout testleri yap.
>
> Accessibility: keyboard, focus, ARIA, contrast, reduced motion.
>
> Playwright ile mobile + desktop critical flow testleri yaz.
>
> `PHASE_23.md` üret.

---

# FAZ 24 - GENEL ADMIN CONTENT STUDIO

## Prompt

> FAZ 24: Item Studio dışındaki bütün game content'i yönetmek için `/admin/content` oluştur.
>
> Modüller:
> - races
> - classes/branches/specializations
> - skills/passives
> - talent trees
> - professions/specializations
> - zones/enemies/bosses
> - drop tables
> - recipes
> - quests
> - titles/achievements
> - localization
> - balance configs
>
> Item Studio'da oluşturulan reusable localization, history, publish, validation ve audit componentlerini yeniden kullan.
>
> Publish workflow:
> Draft -> Validation -> Review -> Published -> Archived.
>
> Content dependency graph göster: örn bir skill'i archive etmek kaç class/talent/item tarafından referanslanıyor. Referanslı content hard delete edilemesin.
>
> “Publish bundle” özelliği ekle: birbirine bağlı class+skill+talent değişiklikleri tek release revision altında yayınlanabilsin.
>
> Admin localization dashboard: locale başına completion %, missing, draft, reviewed; filtre ve export/import.
>
> `PHASE_24.md` üret.

---

# FAZ 25 - BALANCE SIMULATOR, BOT PROFILES VE TELEMETRY

## Prompt

> FAZ 25: Oyun çıkmadan dengeyi ölçebileceğimiz simulator geliştir.
>
> Backend/CLI balance simulator:
> - level seç
> - race
> - class/specialization
> - talent build
> - gear budget/tier
> - zone/enemy
> - risk mode
> - AFK duration
> - iterations/seeds
>
> Metrics:
> - kills/hour
> - XP/hour
> - loot value/hour
> - death probability
> - potion/resource consumption
> - DPS/HPS
> - effective damage taken
> - support contribution
> - profession yield/hour
>
> Class/race balance checker:
> - racial combat advantage approx %3-5 limit warning
> - support solo kill speed target pure DPS'in %70-80 bandı
> - tier stat outliers
> - impossible item requirement
> - dominant specialization/talent warning
>
> Admin dashboard charts oluştur fakat grafikler karar aracı olsun; otomatik balance değişikliği yapma.
>
> Player telemetry privacy-conscious ve aggregate olsun: session completion, death, zone choice, profession usage, abandonment funnel. Gereksiz kişisel veri toplama.
>
> Simulator sonuçları CSV/JSON export edilebilsin.
>
> `PHASE_25.md` üret.

---

# FAZ 26 - SECURITY, ANTI-CHEAT, IDEMPOTENCY VE EXPLOIT AUDIT

## Prompt

> FAZ 26: Tüm oyun ekonomisi ve progression için security pass yap.
>
> Threat model oluştur:
> - duplicate AFK claim
> - clock manipulation
> - client damage/XP forgery
> - item duplication
> - crafting double-spend
> - market race condition
> - replay request
> - admin privilege escalation
> - CSV import injection
> - arbitrary effect payload
> - negative/overflow values
> - API scraping/rate abuse
>
> Server time haricinde client timestamp'a güvenme.
>
> Idempotency key infrastructure kritik mutating endpointlere uygula.
>
> Redis locks tek güvenlik katmanı olmasın; DB unique constraints/transactions ile destekle.
>
> Economy/progression audit ledger ve suspicious-event logging ekle.
>
> Admin 2FA/step-up auth için destek veya güçlü extension point oluştur; production configte zorunlu hale getirilebilir.
>
> Dependency/security scan, CORS/CSRF/cookie headers, SQL injection ve XSS kontrollerini gözden geçir.
>
> Automated abuse tests oluştur.
>
> `docs/security/THREAT_MODEL.md` ve `PHASE_26.md` üret.

---

# FAZ 27 - PERFORMANCE VE LOAD TEST

## Prompt

> FAZ 27: Performans ve ölçek testleri yap. AFK mimarisinin gerçek worker loop kullanmadığını doğrula.
>
> Test senaryoları:
> - yüksek eşzamanlı login/read traffic
> - binlerce expired AFK session claim
> - item search/filter 1,520+ template
> - market purchase contention
> - admin bulk import
> - combat simulator batch
>
> DB index audit yap. N+1 query bul ve düzelt. Slow query logging geliştir.
>
> Cache yalnızca doğruluk bozmayan read paths'te kullan. Published content cache version-aware invalidation yapsın.
>
> AFK resolution CPU profiling yap; event stepping optimize et. Tek session 3 saatlik süreyi 3 saat gerçek zaman beklemeden kısa sürede çözmeli.
>
> Rate limit ve backpressure sınırlarını ölç.
>
> Baseline performance raporu `docs/performance/BASELINE.md` yaz.
>
> `PHASE_27.md` üret.

---

# FAZ 28 - FULL TEST MATRIX VE REGRESSION

## Prompt

> FAZ 28: Production öncesi tam test ve regression fazı.
>
> Backend unit/integration coverage kritik domainlerde yüksek olsun: progression, stat calculator, effects, combat, AFK, item requirement, item roll, profession, craft, economy, market.
>
> Property-based test uygun yerlerde kullan: stat allocation, item roll bounds, loot weights, XP cap, currency invariants.
>
> Golden seed tests: aynı snapshot+seed her zaman aynı AFK sonucu.
>
> E2E akışlar:
> 1. register -> character create -> race/class select
> 2. stat allocate
> 3. start/claim AFK
> 4. equip loot
> 5. promotion
> 6. talent allocation
> 7. profession task/craft
> 8. market
> 9. language switch four locales
> 10. admin create item -> translate -> publish -> player sees it
>
> Database migration from fresh install ve sequential upgrade test et.
>
> Browser/mobile viewport matrix çalıştır.
>
> `docs/testing/REGRESSION_MATRIX.md` ve `PHASE_28.md` üret.

---

# FAZ 29 - DEPLOYMENT, BACKUP, OBSERVABILITY VE RELEASE

## Prompt

> FAZ 29: Production deployment hazırlığı.
>
> Docker production images multi-stage ve non-root olsun. Dev/prod settings ayrımı yap.
>
> Reverse proxy/TLS deployment dokümantasyonu oluştur. Secrets environment/secret store üzerinden gelsin.
>
> PostgreSQL automated backup/restore procedure; backup verification ve restore drill script yaz.
>
> Observability:
> - structured logs
> - error tracking integration interface
> - metrics: request latency/error, AFK resolve duration/error, DB pool, Redis, economy anomaly counters
> - health/readiness endpoints
>
> Migration deployment strategy ve rollback dokümanı oluştur.
>
> Seed/catalog import release sırasında idempotent olsun.
>
> `docs/operations/RUNBOOK.md`, `BACKUP_RESTORE.md`, `RELEASE_CHECKLIST.md` üret.
>
> `PHASE_29.md` üret.

---

# FAZ 30 - FINAL GAME DESIGN / CODE CONSISTENCY AUDIT

## Prompt

> FAZ 30: Kod yazmadan önce tüm repository'yi ve `Oldschool_AFK_Text_MMO_Game_Design.pdf` tasarımını tekrar oku. Tasarım ile uygulama arasında final consistency audit yap ve gerekli düzeltmeleri uygula.
>
> Özellikle doğrula:
> - Character cap 1000
> - Profession cap 500
> - 3 stat point/level
> - 7 stat ve soft caps
> - 8 race
> - 10 base class
> - 20 Lv100 path
> - exactly 40 Lv300 specialization
> - Lv600 Awakening
> - Lv850 talent capstone
> - Lv1000 mastery
> - class başına 3 talent tree, 45 total, 25 max/tree
> - 15 professions, Lv200 specialization
> - max 3 profession specialist license
> - max AFK 3h
> - daily efficiency bands
> - passive-first + Active Tactics
> - T0-T10 item tiers
> - 1,520 functional launch item hedefi
> - EN/TR/ZH-CN/ES
> - Item Studio tüm gerekli alanları yönetiyor
> - server-authoritative, deterministic claim
>
> Orphan localization, dead content references, unreachable talent node, invalid drop table, impossible item, duplicate code, missing translation ve migration drift taraması yap.
>
> Sonrasında `docs/FINAL_AUDIT.md` oluştur:
> - Pass/Fail checklist
> - known issues
> - launch blockers
> - post-launch improvements
>
> Bütün test/lint/type/build/load-smoke adımlarını tekrar çalıştır. Fail varsa düzeltmeden tamamlandı deme.
>
> `PHASE_30.md` üret.

---

# OPSİYONEL FAZ 31 - GUILD, RAID VE SOSYAL SİSTEM

Core oyun stabil olduktan sonra.

## Prompt

> Guild oluşturma, guild rank/permission, guild treasury audit, guild achievements ve 10-20 kişilik raid encounter modelini geliştir. Support sınıflarının raid katkısını damage dışındaki metriklerle ölç. Guild sistemi economy duplication veya alt-account abuse üretmeyecek limitlere sahip olsun. Chat moderation/report contract oluştur. Bu faz core progression'ı değiştirmesin.

---

# OPSİYONEL FAZ 32 - PVP / ARENA

Core PvE dengesi oturduktan sonra.

## Prompt

> PvE coefficientlerini bozmadan ayrı PvP coefficient layer oluştur. Arena snapshot bazlı server-authoritative çalışsın. Matchmaking/rating sistemi ayrı domain olsun. PvP'de hard stun/one-shot/regen gibi mekanikler için ayrı balance config kullan. Race/class seçimlerinin zorunlu meta olmasını engellemek için simulator ile distribution raporu üret. İlk sürümde ranked 1v1/3v3 gibi dar kapsamla başla; open-world PvP ekleme.

---

# ADMIN ITEM STUDIO - HIZLI WIREFRAME

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ADMIN / ITEM STUDIO     Search [____________]   + NEW   GENERATOR   IMPORT │
├──────────────────┬───────────────────────────────────────┬───────────────────┤
│ FILTERS          │ ITEM TABLE                            │ QUICK INSPECTOR   │
│                  │                                       │                   │
│ Status           │ Code | Name | T | Rarity | Slot ... │ Iron Bastion...   │
│ Category         │ ------------------------------------- │ T7 Legendary      │
│ Tier             │ itm_001 ...                           │ Heavy Shield      │
│ Rarity           │ itm_002 ...                           │ Lv 600            │
│ Slot             │ itm_003 ...                           │                   │
│ Class Tag        │ ...                                   │ [EDIT] [CLONE]    │
│ Profession       │                                       │ [HISTORY]         │
│ Translation      │                                       │                   │
└──────────────────┴───────────────────────────────────────┴───────────────────┘
```

Full item editor:

```text
GENERAL | LOCALIZATION | REQUIREMENTS | STATS & EFFECTS | AFFIXES
UNIQUE/SET | SOCKETS/UPGRADE | SOURCES | CRAFT/SALVAGE | PREVIEW | HISTORY
```

Bu yapı özellikle item sayısı 1,500'ü geçtiğinde düz form yaklaşımından daha verimlidir.

---

# OTOMATİK FAZ KAPANIŞ KURALI

> Her faz sonunda uygulamayı kendin code-review et. `CLAUDE.md`, canonical rules ve ilgili fazın acceptance criteria'sını kontrol et. Placeholder, TODO, hardcoded localization, race condition, idempotency açığı, migration eksikliği, N+1 query veya test edilmeyen kritik path varsa düzelt. Ardından gerekli lint, type-check, backend/frontend testleri ve build kalite kapısını çalıştır. Yalnızca kalite kapısı başarılıysa faz raporunu ve `.claude/state.json` durumunu güncelle; kullanıcı onayı beklemeden bir sonraki zorunlu faza geç.

---

# UYGULAMA SIRASI - KISA ÖZET

| Faz | Konu |
|---|---|
| 00 | CLAUDE.md + architecture rules |
| 01 | Monorepo + Docker |
| 02 | 4-language i18n |
| 03 | Auth/RBAC/Character shell |
| 04 | Content/version/effect engine |
| 05 | Level/stat/progression |
| 06 | Races |
| 07 | Classes + 40 specialization |
| 08 | Skills/passives/talents |
| 09 | Combat core |
| 10 | Passive-only combat |
| 11 | Active Tactics |
| 12 | Zones/enemies/bosses |
| 13 | AFK engine |
| 14 | Item domain |
| 15 | Admin Item Studio |
| 16 | Inventory/equipment |
| 17 | Professions |
| 18 | Gathering/crafting |
| 19 | Loot + 1,520 item generator |
| 20 | Economy/market |
| 21 | Party/group AFK |
| 22 | Quest/title/prestige |
| 23 | Player UI/PWA |
| 24 | General Content Studio |
| 25 | Balance simulator/telemetry |
| 26 | Security/anti-cheat |
| 27 | Performance/load |
| 28 | Full regression |
| 29 | Deployment/operations |
| 30 | Final design/code audit |
| 31 | Optional Guild/Raid |
| 32 | Optional PvP/Arena |

