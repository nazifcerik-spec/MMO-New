# CANONICAL RULES — Oldschool AFK Text MMORPG

Source: `docs/design/Oldschool_AFK_Text_MMO_Game_Design.pdf` (GDD v1.0) + phase plan core rules.
Game facts only. Internal codes are English, snake_case, immutable. Numeric balance values live in
content/config data (`backend/app/content/data/`) — this file is the reference they must match.

## 1. Core caps
| Rule | Value |
|---|---|
| Character level cap | 1000 |
| Profession level cap | 500 (per profession, independent of character level) |
| Stat points per character level gained | 3 (Lv1000 → 2,997 distributable) |
| Class breakpoints | 100, 300, 600, 850, 1000 |
| AFK single command max | 3 h (10,800 s) |
| Daily efficiency bands (per player-day, UTC) | 0–9 h 100%, 9–12 h 80%, 12–18 h 50%, 18–24 h 25% |
| Daily optimum | 9 h (3 × 3 h) |
| Active Specialist Profession Licenses | max 3 |
| Talent points (at Lv1000) | 45 total, max 25 per tree, 3 trees per base class |
| Talent capstone | 25 points in the tree + character Lv850; only one capstone possible |
| Item tiers | T0–T10 |
| Launch functional item target | 1,520 |
| Races | 8, no class locks |
| Base classes | 10 (5 combat + 5 support) → 20 Lv100 paths → exactly 40 Lv300 specializations |
| Priority professions | 15 |
| Combat model | Passive-first + optional Active Tactics (HYBRID launch default) |
| Active kit limit (Active Tactics) | max 5 core actives + 1 ultimate per specialization |
| Support solo parity | solo support kill speed ≈ 70–80% of pure DPS, higher sustain |
| Solo Accord | outside a party, 35% of support power converts to attack/spell power (config) |
| Racial combat advantage | total ≈ 3–5% max (validator) |
| Item gate rule | total stat requirement ≤ 60–70% of average distributable points at that level |
| Post-Lv1000 | horizontal only: mastery, titles, collections, professions, relics, seasons |

## 2. Stats
Codes: `STR DEX INT VIT WIS SPI LUK`.
- STR: melee attack, heavy weapon scaling, carry
- DEX: attack speed, accuracy, dodge, crit
- INT: spell power, magic penetration, mana efficiency
- VIT: HP, armor efficiency, stun resistance
- WIS: healing power, shield power, mana regen
- SPI: buff/debuff power, resource regen, pet/totem scaling
- LUK: crit variance, rare drop modifier (small, diminishing), proc consistency

Soft-cap effectiveness per point, by allocated band of a single stat:
0–300 → 1.00, 301–600 → 0.70, 601–900 → 0.45, 901+ → 0.25.

Auto stat profiles (`stat_profile` codes):
- `tank`: VIT 45%, main 30%, utility 15%, LUK 10%
- `physical_dps`: main 50%, DEX/LUK 25%, VIT 15%, utility 10%
- `caster_dps`: INT 50%, SPI 25%, WIS/VIT 15%, LUK 10%
- `healer`: WIS 45%, SPI 35%, VIT 15%, LUK 5%
- `hybrid_support`: SPI 40%, WIS 25%, main damage 20%, VIT 15%

Class stat weights (primary / secondary / defensive-utility):
warrior STR/VIT/DEX · rogue DEX/LUK/VIT · ranger DEX/LUK/SPI · mage INT/SPI/WIS · monk DEX/SPI/VIT ·
cleric WIS/SPI/VIT · paladin VIT/WIS/STR · druid WIS/SPI/VIT · bard SPI/DEX/WIS · shaman SPI/WIS/INT

## 3. Levels, stages, titles
Stages: 1–99 Origin (Adventurer) · 100–299 First Promotion · 300–599 Specialization · 600–849 Awakening ·
850–999 Mastery (capstone) · 1000 Class Mastery.

Level title ladder (min level → code/name): 1 `novice` · 100 `veteran` · 200 `seasoned` · 300 `elite` ·
400 `heroic` · 500 `legendary` · 600 `champion` · 700 `mythic` · 800 `ancient` · 850 `ascendant` ·
900 `immortal` · 950 `exalted` · 1000 `eternal`.

Time-to-level targets (XP curve must approximate): 1–100 ≈8 h · 101–300 ≈48 h · 301–600 ≈209 h ·
601–800 ≈277 h · 801–900 ≈193 h · 901–1000 ≈233 h · total ≈968 h (≈108 days at 9 h/day).

Class title transformation (generic): Lv1 base class → Lv100 branch → Lv300 specialization →
Lv600 "Awakened <spec>" → Lv850 "Ascendant <spec>" → Lv1000 "Eternal <mastery noun>" (e.g. Eternal Bastion).

Status rarity (prestige presentation only, not power): bronze, silver, gold, platinum, mythic, relic.

## 4. Races (code — trait — race title — effects)
1. `human` — Adaptable — Diplomat — all XP +3%; reduced stat respec cost for first 300 points
2. `high_elf` — Arcane Blood — Starborn — INT +4%, mana regen +5%, elemental resist +3%
3. `dark_elf` — Night Instinct — Umbral — DEX +4%, crit damage +5%, debuff duration +4%
4. `dwarf` — Stoneborn — Deepforged — VIT +5%, block efficiency +5%, Mining speed +8%
5. `orc` — Blood Fury — Warborn — STR +5%, damage +6% below 35% HP, healing received −2%
6. `sylvan` — Nature Bond — Greenwarden — WIS +4%, HoT +5%, Herbalism/Fishing +6%
7. `beastkin` — Predator Sense — Wildblood — DEX +3%, LUK +3%, dodge +3%, Hunting +8%
8. `revenant` — Undying Will — Deathless — SPI +4%, death penalty −25%, lifesteal effectiveness +4%

Natural affinity (informational only): human all; high_elf mage/cleric/druid; dark_elf rogue/ranger/bard;
dwarf warrior/paladin/shaman; orc warrior/monk/shaman; sylvan druid/ranger/cleric;
beastkin rogue/ranger/monk; revenant warrior/mage/shaman.

## 5. Classes (base → Lv100 branches → Lv300 specializations → Lv600 awakening)
Category, resource, talent trees (with capstone), weapons.

| Base | Cat | Resource | Branch A → specs | Branch B → specs | Talent trees (capstone) |
|---|---|---|---|---|---|
| warrior | combat | rage | guardian → iron_bastion, warlord | reaver → berserker, weapon_master | defense (Living Fortress), arms (Perfect Technique), blood (Blood Frenzy) |
| rogue | combat | energy + opportunity | assassin → nightblade, venomancer | duelist → blade_dancer, trickster | assassination (Perfect Kill), combat (Blade Storm), trickery (Untouchable) |
| ranger | combat | focus | marksman → sharpshooter, arbalist | scout → beastmaster, trapper | marksmanship (Perfect Shot), beastcraft (Alpha Bond), survival (Master Hunter) |
| mage | combat | mana + arcane_charge | arcanist → runemaster, chronomancer | elementalist → pyromancer, cryomancer | arcane (Arcane Singularity), element (Elemental Avatar), control (Time Stop) |
| monk | combat | chi | disciple → iron_body, spirit_walker | striker → combo_master, storm_fist | body (Diamond Body), technique (Perfect Technique), chi (Infinite Flow) |
| cleric | support | faith | saint → high_priest, aegis_priest | oracle → prophet, exorcist | restoration (Miracle), barrier (Divine Fortress), faith (Divine Presence) |
| paladin | support | conviction | warden → aegis_knight, lightwarden | crusader → templar, justicar | aegis (Divine Bastion), aura (Holy Presence), judgment (Final Judgment) |
| druid | support | nature_essence | grovekeeper → lifebinder, thorn_sage | shapeshifter → bearwarden, mooncaller | growth (World Tree), wild (Primal Avatar), nature (Nature's Wrath) |
| bard | support | rhythm | minstrel → virtuoso, harmonist | skald → war_chanter, dirge_singer | melody (Grand Symphony), rhythm (Battle Anthem), discord (Final Dirge) |
| shaman | support | spirit_charges | totemist → earthwarden, storm_totemist | spiritcaller → ancestor_sage, hexer | totem (Totemic Dominion), ancestor (Ancestor's Blessing), element (Spirit Storm) |

Talent tree codes are namespaced per class in data (`<class>.<tree>`, e.g. `mage.element`, `shaman.element`).

Weapons: warrior sword, axe, mace, greatsword, greataxe, spear, shield · rogue dagger, shortsword,
dual_daggers, fist_weapon, throwing_knife · ranger bow, longbow, crossbow, short_spear · mage staff, wand,
orb, grimoire · monk fist_weapon, staff, tonfa, unarmed · cleric staff, mace, holy_tome, shield ·
paladin sword, mace, two_handed_mace, shield · druid staff, sickle, nature_focus · bard lute, harp, flute,
rapier · shaman staff, ritual_axe, mace, totem.

Base passives, Lv100 path passives, Lv300 passives, Lv600 awakenings and 5 actives + 5 core passives per
class are seeded from GDD §06–07 verbatim (see `backend/app/content/data/classes.yaml`).
Key numeric Lv100 passives: guardian Armor +12%, Block +8%, Threat +10% · reaver +15% dmg vs <35% HP ·
assassin first-hit crit dmg +25% · marksman ranged dmg +12% · scout dodge +8% · arcanist mana cost −8%,
cooldown −5% · elementalist element dmg +10% · disciple chi regen +10%, healing received +6% ·
saint healing +15% · oracle buff/cleanse duration +15% · warden block +8% · crusader holy dmg +10% ·
grovekeeper HoT +12%, root duration +8% · shapeshifter form bonus +12% · minstrel song duration +15% ·
skald offensive song power +12% · totemist totem radius +12%, duration +10% · spiritcaller spirit gen +12%.

Solo Accord (all 5 support classes): outside a party, 35% of support power converts to attack/spell power.
Solo Accord turns off automatically in a party.

## 6. Talents
Tiers by points spent in tree: I 1–5, II 6–10, III 11–15, IV 16–20, V 21–24, Capstone 25 (+Lv850).
Reference archetypes: Pure 25/15/5, Hybrid 20/15/10, Utility 15/15/15, Specialist 25/10/10.
Reset cost: < Lv300 free/very cheap; Lv300–599 medium; Lv600+ gold + rare material.

## 7. Combat
- Passive-only layers: base attack, stance (`aggressive`/`guarded`/`efficient`), trigger passive,
  threshold passive, cycle passive (every N), target rule, consumable rule.
- Active Tactics: up to 6 priority rules; canonical: HP<35% → defensive/heal; boss → single-target
  finisher; enemies ≥3 → AoE; resource >70% → spender; cooldown ready → buff/debuff; fallback basic attack.
- Game modes: `PASSIVE_ONLY`, `ACTIVE_TACTICS`, `HYBRID` (launch default HYBRID; ordinary AFK passive-first).

## 8. AFK
Configurable at start: zone, target priority, stance, potion threshold, loot filter, skill priority or
passive profile, profession task, risk level.
Risk profiles (XP/loot multiplier): `safe` 85% very low death · `balanced` 100% medium ·
`dangerous` 120% high · `elite_hunt` 135% + rare chance, very high.
Death is friction, not loss: lose efficiency of roughly the last 15–30 min, durability, small recovery cost.
3-Hour Satisfaction Rule: every max session yields ≥1 visible progress signal.
Catch-up allowed (old-tier XP bonus, rested XP, low-level profession bonus); Lv850+ prestige not accelerated.

## 9. Professions (code — type — tool — stats — Lv200 specs A/B — Lv500 title)
| code | type | tool | stats | spec A / spec B | Lv500 title |
|---|---|---|---|---|---|
| mining | gathering | pickaxe | STR/VIT | prospector / deep_miner | Grandmaster Miner |
| logging | gathering | axe | STR/VIT | forester / resin_harvester | Grandmaster Lumberjack |
| fishing | gathering | rod | DEX/LUK | angler / pearl_diver | Grandmaster Angler |
| hunting | gathering | knife/bow | DEX/LUK | tracker / trophy_hunter | Grandmaster Hunter |
| herbalism | gathering | sickle | WIS/LUK | botanist / seedkeeper | Grandmaster Herbalist |
| blacksmithing | crafting | forge_hammer | STR | refiner / master_forger | Grandmaster Blacksmith |
| weaponsmithing | crafting | forge_kit | STR/DEX | edge_master / impact_smith | Grandmaster Weaponsmith |
| armorsmithing | crafting | forge_kit | STR/VIT | bulwark_smith / plate_artisan | Grandmaster Armorsmith |
| leatherworking | crafting | leather_tools | DEX | tanner / hide_artisan | Grandmaster Leatherworker |
| tailoring | crafting | needle_kit | WIS/DEX | weaver / mystic_tailor | Grandmaster Tailor |
| jewelcrafting | crafting | jeweler_kit | LUK/DEX | gemcutter / runesetter | Grandmaster Jeweler |
| alchemy | crafting | alchemist_kit | INT/WIS | elixirist / toxicologist | Grand Alchemist |
| cooking | crafting | cookware | WIS | provisioner / feastmaster | Master Culinarian |
| enchanting | crafting | arcane_focus | INT/SPI | imbuer / disenchanter | Grand Enchanter |
| engineering | crafting | toolbox | INT/DEX | mechanist / trapwright | Master Engineer |

Ranks: 1–99 `apprentice` · 100–199 `journeyman` · 200–299 `expert` (specialization choice) ·
300–399 `artisan` · 400–499 `master` · 500 `grandmaster`.
Crafting quality (separate from rarity): `common → fine → superior → masterwork → mythic_crafted`.
Stats affect time/quality chance, never hard-lock content. Low tool tier in high zone → heavy yield loss.
Specialist License swap has cooldown + cost.

## 10. Items
Categories and launch counts: weapons 280 · armor 360 · accessories 120 · profession_tools 90 ·
consumables 160 · materials 240 · recipes 120 · quest_key_token 80 · cosmetic_collectible 70 = 1,520.

Tier gates (min–max character level, rarity band, suggested total stat requirement):
T0 1–49 worn/common 0–40 · T1 50–99 common/fine 40–80 · T2 100–199 fine/rare 80–150 ·
T3 200–299 rare 150–230 · T4 300–399 rare/epic 230–320 · T5 400–499 epic 320–410 ·
T6 500–599 epic/legendary 410–500 · T7 600–699 legendary 500–590 · T8 700–849 legendary/mythic 590–720 ·
T9 850–949 mythic 720–830 · T10 950–1000 mythic/relic 830–900.

Rarity chain: `common → fine → rare → epic → legendary → mythic → relic` (`worn` = starter only, outside chain).
Affix budget: common 0–1 · fine 1–2 · rare 2–3 · epic 3–4 (≤1 class-tag affix) · legendary 4–5 + unique
effect · mythic 5–6 + unique + mastery scaling · relic fixed, build-changing, very limited.

Requirement profiles (primary/secondary, Lv600 example): heavy_weapon STR/VIT 470+140 · finesse_weapon
DEX/LUK 470+120 · caster_weapon INT/SPI 470+130 · healing_focus WIS/SPI 450+160 · heavy_armor VIT/STR
430+140 · light_armor DEX/VIT 380+170 · cloth_armor INT|WIS/SPI 390+160 · support_relic SPI/WIS 420+160.

Class item tags: vanguard (tank/block/HP), slayer (physical DPS/execute), shadow (crit/poison/dodge),
hunter (ranged/pet/trap), arcane (spell/mana/rune), faith (heal/barrier), harmony (buff/song/aura),
primal (form/nature/sustain), spirit (totem/debuff/resource).

## 11. Economy sinks
repair, respec, specialist license swap, crafting quality attempts, enchant reroll, cosmetic prestige.

## 12. Locales
Exactly `en`, `tr`, `zh-CN`, `es`. Fallback: selected → `en` → safe internal label.
