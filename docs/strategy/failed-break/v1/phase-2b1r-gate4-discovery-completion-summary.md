# Phase 2B.1R Gate 4 — Discovery Completion Summary (read-only)

Generated 2026-08-30 after Wave 6 (Outcome A). This document is analysis only.
It creates **no** approval, registration, sealing record, data contract, or
replacement acquisition plan. Discovery completion is an operational fact;
inventory approval is a separate, unauthorized human decision (Gate 5).

- Database: `trade_recommender_research`
- Commit: `e9e852e3dc527db30d9a64cf87cedbea57b8c5a6`
- V2 plan SHA-256: `2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a`
- V2 request-manifest SHA-256: `04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427`
- Wave-manifest SHA-256: `8e75440d94a2045ddbdb5b9949dc9a089ae1eb79e3fe844cd102691e8a747a39`
- Immutable lineage hash (unchanged since canary):
  `f3b6884db0c84ba1ff6b103bfe42d405888dcf7e6fb8ac1b8f943126e616e5bc`

## Global identities (reconstructed read-only, registration conventions)

- Ordered chunk-manifest hash: `04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427`
  (reconstructs the plan's declared request manifest exactly)
- **Global semantic-inventory SHA-256 (132 rows, ordinal order):**
  `78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c`
- **Ordered operational-evidence-set SHA-256 (all 133 v2-plan attempts,
  ordered by ordinal then attempt number, including the one failed
  predecessor — canary attempt 1):**
  `a650dd977f0f2c79cbad2cb476fe36610a0fc0c2f372107b541882d0b342c878`

## Ledger state at completion

| Metric | Value |
|---|---|
| Chunks / successful inventories | 132 / 132 |
| Eligible chunks remaining | 0 |
| Permanently closed chunks | 132 |
| Attempts (all plans) | 134 (v2 plan: 133 = 131×1 + canary×2) |
| Runs / audit events | 142 / 141 |
| Running attempts | 0 |
| Observations (total) | 364,953 |
| Sealed / approvals / registrations / data contract | 0 / 0 / 0 / absent |
| Scheduled jobs enabled | 0 |
| Privacy scan | PASS |

## Per-series inventory (instrument × granularity)

All series: incomplete = 0, missing bid/ask = 0, zero-volume = 0.

| Instrument | Gran | Inventories | Observations | First (UTC) | Last (UTC) | NY-weekend |
|---|---|---|---|---|---|---|
| AUD_USD | D | 1 | 2,891 | 2009-02-26T22:00 | 2018-12-30T22:00 | 714 |
| EUR_GBP | D | 1 | 2,907 | 2009-02-26T22:00 | 2018-12-30T22:00 | 714 |
| EUR_USD | D | 1 | 2,911 | 2009-02-26T22:00 | 2018-12-30T22:00 | 714 |
| GBP_USD | D | 1 | 2,902 | 2009-02-26T22:00 | 2018-12-30T22:00 | 713 |
| USD_CAD | D | 1 | 2,894 | 2009-02-26T22:00 | 2018-12-30T22:00 | 713 |
| USD_JPY | D | 1 | 2,907 | 2009-02-26T22:00 | 2018-12-30T22:00 | 714 |
| AUD_USD | H1 | 20 | 57,474 | 2009-12-31T15:00 | 2018-12-31T21:00 | 4,585 |
| EUR_GBP | H1 | 20 | 57,430 | 2009-12-31T15:00 | 2018-12-31T21:00 | 4,534 |
| EUR_USD | H1 | 20 | 57,521 | 2009-12-31T15:00 | 2018-12-31T21:00 | 4,618 |
| GBP_USD | H1 | 20 | 57,439 | 2009-12-31T15:00 | 2018-12-31T21:00 | 4,546 |
| USD_CAD | H1 | 20 | 57,405 | 2009-12-31T15:00 | 2018-12-31T21:00 | 4,514 |
| USD_JPY | H1 | 20 | 57,446 | 2009-12-31T15:00 | 2018-12-31T21:00 | 4,546 |
| AUD_USD | W | 1 | 471 | 2009-12-18T22:00 | 2018-12-21T22:00 | 0 |
| EUR_GBP | W | 1 | 471 | 2009-12-18T22:00 | 2018-12-21T22:00 | 0 |
| EUR_USD | W | 1 | 471 | 2009-12-18T22:00 | 2018-12-21T22:00 | 0 |
| GBP_USD | W | 1 | 471 | 2009-12-18T22:00 | 2018-12-21T22:00 | 0 |
| USD_CAD | W | 1 | 471 | 2009-12-18T22:00 | 2018-12-21T22:00 | 0 |
| USD_JPY | W | 1 | 471 | 2009-12-18T22:00 | 2018-12-21T22:00 | 0 |

Totals: D 17,412 (weekend 4,282) · H1 344,715 (weekend 27,343) · W 2,826
(weekend 0) → **364,953**.

## Provider-history changes across years (H1, all six instruments)

| Year | Obs | NY-weekend | EST (−18000) | EDT (−14400) |
|---|---|---|---|---|
| 2009 | 48 | 0 | 48 | 0 |
| 2010 | 38,868 | 3,385 | 13,555 | 25,313 |
| 2011 | 43,570 | 7,573 | 14,334 | 29,236 |
| 2012 | 38,591 | 3,335 | 13,323 | 25,268 |
| 2013 | 37,372 | 2,256 | 12,876 | 24,496 |
| 2014 | 37,253 | 2,184 | 12,773 | 24,480 |
| 2015 | 37,266 | 2,184 | 12,780 | 24,486 |
| 2016 | 37,290 | 2,142 | 12,810 | 24,480 |
| 2017 | 37,158 | 2,100 | 12,666 | 24,492 |
| 2018 | 37,299 | 2,184 | 12,819 | 24,480 |

Reading: 2010–2012 include substantial true Saturday/Sunday trading hours
(2011 peaks at 7,573). From 2013 onward, weekend observations collapse to a
stable ~2,100–2,260 per year — 2,184 = 7 Sunday-evening hours (17:00–23:00
NY) × 52 weeks × 6 instruments, i.e. exactly the standard Sunday 5 p.m. NY
session open. This is a provider-side history regime change, not a defect.
DST offsets are exclusively −18000 (EST) and −14400 (EDT); no third offset
appears anywhere. Only 48 observations fall in 2009 for H1 (the requested
window opens 2009-12-31T15:00Z; hours 15:00–22:00 are present for all six
instruments and 23:00 is absent for all six — New Year's Eve close).

## Cross-instrument H1 timestamp-set comparison

- Union of all six instruments' timestamp sets: **57,692** distinct hours.
- Common to all six: **57,266** (99.26% of the union).
- Per-instrument set sizes and hours unique to that instrument alone:
  AUD_USD 57,474 (54 unique) · EUR_GBP 57,430 (2) · EUR_USD 57,521 (80) ·
  GBP_USD 57,439 (14) · USD_CAD 57,405 (16) · USD_JPY 57,446 (16).
- Pairwise symmetric differences range from 84 (EUR_GBP↔USD_JPY) to 259
  (AUD_USD↔EUR_USD). EUR_USD is the most idiosyncratic calendar; EUR_GBP the
  most "core".

Interpretation: the six calendars are near-identical but **not** identical.
Chunk-boundary micro-gaps (e.g. 2011-05-15T15:00Z absent between ordinals
48/49) recur at the same instants across instruments, indicating
provider-side gaps rather than per-request faults.

## Unresolved observations requiring human judgment (no defects found)

1. **Weekend-regime shift (2010–2012 vs 2013+):** downstream strategy code
   must decide whether weekend hours are tradable, filtered, or flagged.
   The inventory records them faithfully; no automated policy was applied.
2. **Per-instrument calendar divergence:** 426 union hours are not common to
   all six instruments. Gate 5 review must accept per-instrument calendars
   (rather than one shared calendar) before any acquisition plan is built.
3. **Provider D series includes Sunday candles** (713–714 weekend days per
   instrument; counts 2,891–2,911 differ per instrument vs the synthetic
   calendar's 2,567) — this was the original supersession rationale and is
   now fully quantified.
4. **W series matches the synthetic calendar exactly** (471 per instrument,
   zero weekend) — no decision needed.
5. **One failed predecessor exists in the operational ledger** (canary
   attempt 1, governed STRUCTURE_INVALID under the superseded v1 H1
   alignment rule, 106 misaligned of 2,932 fetched). It is preserved
   immutably and included in the operational-evidence-set hash.

## Gate 5 readiness assessment

READY FOR HUMAN INVENTORY REVIEW. All 132 chunks hold accepted inventories
produced by exactly one attempt each (plus the governed canary retry);
every stored hash reconstructs independently at every layer (timestamp-set,
structural, semantic, operational, event); the operational ledger is
complete with zero running attempts; the canary/plan/supersession lineage
hash is byte-identical to its post-canary value; the privacy scan passes;
both plans remain unsealed and no approval, registration, data contract, or
acquisition plan exists. The two global identities above are the exact
values a future approval/registration would compute.

## Per-chunk semantic-inventory hashes (all 132, ordinal order)

| Ordinal | Instrument | Gran | Obs | Semantic-inventory SHA-256 |
|---|---|---|---|---|
| 1 | AUD_USD | D | 2891 | `c21bc36df1c88c8c517a825c011173cebd175bc4c10e81126a3b6debdf5497d3` |
| 2 | AUD_USD | H1 | 2932 | `fdf82569dc323bc58cadb5b48d5309fc0ec987c5caf66e16a1225d478b09e9de` |
| 3 | AUD_USD | H1 | 2957 | `6af4b0a083ffb26a83542b38eebae44d5019fd31c096c60bac2fba396857a6b8` |
| 4 | AUD_USD | H1 | 3293 | `03cc5e18d655a7c01d236b04bf59799e61a4b2113b6e81d5e713daa67ab2279d` |
| 5 | AUD_USD | H1 | 3447 | `a6e9d5b25c273027b94dda8df7cd95775099982933e8d40f6807457fd509edce` |
| 6 | AUD_USD | H1 | 2992 | `2072d2e987e7b0e87dc3a012ab4cf586054ae10bdc4baef90e7ff7a582987fd0` |
| 7 | AUD_USD | H1 | 2950 | `062abaa2ed95b161bbb7bf7d92dc8d2ea91bc2cfa522cdc94d1661826551eeaa` |
| 8 | AUD_USD | H1 | 2832 | `3864cf591917cd2139baefc864de43f9c9dbed674b8f10d74ac0b8f2778bfa74` |
| 9 | AUD_USD | H1 | 2850 | `b79a2f3bac6d9bef901f69f4782948aa43bc661b4362255829115d34a544b1f4` |
| 10 | AUD_USD | H1 | 2825 | `716eb23830e6fd081bbbc2a46d9be397af753a925ffd1d3c635c0c44b38c3e06` |
| 11 | AUD_USD | H1 | 2865 | `5c98620edc1014558323435d1003e47475cc16a33e6fd5cb433f81748a89e939` |
| 12 | AUD_USD | H1 | 2793 | `049b33c333009f132c10d2bc872f26b56aa6fc7999020c02dcd18049cea59d61` |
| 13 | AUD_USD | H1 | 2849 | `01e3460d9247c877dfe4a5df760aa1ad5cc9fe3d52487b8bc234798a22d7b07d` |
| 14 | AUD_USD | H1 | 2848 | `31f315effe096de38d3ccd848ea9b9351868f003824802dd84771669cfb99355` |
| 15 | AUD_USD | H1 | 2817 | `7ff45bbbb90e5ac4ea5f497bfef05fb99203669d23a1d2e46964f16832bea71a` |
| 16 | AUD_USD | H1 | 2874 | `ee5da4c2a03db1da9acd72bbe686e4a0d45fc9b169306baa44256d1cc586d4d4` |
| 17 | AUD_USD | H1 | 2798 | `0d209bd553be13d69bad260c3e0850f43e2f80be948cd6f1bb6862b6e7e65a48` |
| 18 | AUD_USD | H1 | 2848 | `c2931509dc79858792c96f66850a6e56767ab78dc09bc7a57d18c60613f8b567` |
| 19 | AUD_USD | H1 | 2802 | `ce68a19ea1f9a6a7925a5440431c1e9cf01bf3bf85d221922dc17bb94c9bf5de` |
| 20 | AUD_USD | H1 | 2862 | `4a8e103d05e1aa2bd8157a15f66096f6ad6264ec23729f0a1d2b351b56dc1c9c` |
| 21 | AUD_USD | H1 | 2040 | `deaae5773cc23b7cab4100f5681f06d60790c49cf250f563a170c573d8de604f` |
| 22 | AUD_USD | W | 471 | `b9c1e3e45817338da44d4ee825d1862a70634ffc1b771a6cb2c783c45e9fc315` |
| 23 | EUR_GBP | D | 2907 | `c9c3500ac674a05ae7fd5b2cca6ab842724296084d7a4160b0f0b476cb0ecc71` |
| 24 | EUR_GBP | H1 | 2932 | `efbb79f9449724c5a0597785f78768b8d5aa3a7583939bbbf5e7deeba6226412` |
| 25 | EUR_GBP | H1 | 2946 | `d93c7cfc97659f1ac4f89393d9e7bf7624286b666bd69859a4b7472882672d01` |
| 26 | EUR_GBP | H1 | 3288 | `cabaaf7bd11afdcf06abe03c3d701afb5f48b8c0e096f559030448a4866165a8` |
| 27 | EUR_GBP | H1 | 3442 | `c4772ca15ab66d5a50b33a604c183ebb527b6b044eb40aea01a290bcc2a19d94` |
| 28 | EUR_GBP | H1 | 2987 | `d13eed70dd5136a6dde73fa464f10daf18b63a9011a6908fb68396caf926cd35` |
| 29 | EUR_GBP | H1 | 2934 | `8ac0d3757e120a959e433eea3ab6140fe0955902d28a9e47d57c3df671eb8306` |
| 30 | EUR_GBP | H1 | 2831 | `17d7e00834a1b98ff439830c2977715286084ec09cecfaf5b95144a9b59abaca` |
| 31 | EUR_GBP | H1 | 2849 | `5671237498b857e7451cb0a92bb956900ffbd2edb8ea6b1bf9853cd5e2006a12` |
| 32 | EUR_GBP | H1 | 2825 | `0276011fee8678677dfb6c662adac375e1c1a3a11b2a3a8dc3d7e4da047607ee` |
| 33 | EUR_GBP | H1 | 2865 | `34468f47955c2719c41d7171c0a83e10f0673d49ecb96c5c32d85851fe62c1e7` |
| 34 | EUR_GBP | H1 | 2793 | `bf08736feef71566e23b2c2d44684853f63bbbfedef287c44a169a64cb4a5274` |
| 35 | EUR_GBP | H1 | 2849 | `c20dbf3a72687bf79b7231e83bceb963b513579d4ef68cff87ee88f3ee482c08` |
| 36 | EUR_GBP | H1 | 2848 | `1c51d6b552ae1cf749bb4cce5495e2ca370c426905abd996fbd2128efacdd5e7` |
| 37 | EUR_GBP | H1 | 2817 | `40a1df4678e11d6a52036abd809f9f52b7d8c6c42eddb578eaac73a8f6dbfb69` |
| 38 | EUR_GBP | H1 | 2874 | `d1a2bca214b6df9a0f4aaa3ea004c19a1f11222a6c0df3b0a1f1b8dd6e6f1d85` |
| 39 | EUR_GBP | H1 | 2798 | `9e51744fc847a19341b167012bd8e47c4e0e6cb095f84d7a71215139fc0afae1` |
| 40 | EUR_GBP | H1 | 2848 | `14df860e010b588d8cfbb4f0b380a9722de2154c23c26b1ebeafd0e0a857a5f9` |
| 41 | EUR_GBP | H1 | 2802 | `50d81ed06fa9a862aa36bdbe68e090480f90660714e5968b9f5f790cbcf8eacc` |
| 42 | EUR_GBP | H1 | 2862 | `ba6fec6456ac58dbd7d5bb5790c3c2b4219cc7726d3f105ef8e465058bc07fb4` |
| 43 | EUR_GBP | H1 | 2040 | `3480fc1f84abd65cf4770d05eca8ba8b99c4fd8071bf20259eca8abac80acdd1` |
| 44 | EUR_GBP | W | 471 | `42c79bb1dcd66a03abfea869b8496ac409ee1f285dbcdcd11cf7ed41be9b39e9` |
| 45 | EUR_USD | D | 2911 | `08f335cc4fff131ee09f0258c4170c0fa6d39a017c0d480d9528841485fa49a9` |
| 46 | EUR_USD | H1 | 2958 | `026743bd035c9e3fd665a2fee2efbfd48789a5c91c90230755464541f0a7291b` |
| 47 | EUR_USD | H1 | 2959 | `cdda18dbf24053aea2220a7debe19a8262d6a4b75c02bb849dc8bde24cfd65aa` |
| 48 | EUR_USD | H1 | 3294 | `d6adaa5375114b7f8c7191797201353c5bcecd2f77f47dce2b1cca6c19ff972f` |
| 49 | EUR_USD | H1 | 3445 | `c8940798bfb3a55ce4b9fe9bf155b909cd728fc7347202b777ce04b5dd0b1cb1` |
| 50 | EUR_USD | H1 | 3001 | `5676f6ad27a14478814c7d32cde3d65cf4753c01df188f7411dee170ef58ca41` |
| 51 | EUR_USD | H1 | 2961 | `706d7cf0ab126da719ef7eda4447e507c4d546c0dd44bd56bb663969326a36ec` |
| 52 | EUR_USD | H1 | 2832 | `302732f190eff9f16b255ec592da481ef2aeac76271e9014f58e0ff6f5dd9760` |
| 53 | EUR_USD | H1 | 2850 | `eb81139ec312892f4e4ea1c48e0304472cdee6cca1d8df0a1b40c9b71a7fb273` |
| 54 | EUR_USD | H1 | 2825 | `140d1b2147ee5602db0a89ea1df3adf6c36d6c2f8d6b69b762ea248d00e06f3d` |
| 55 | EUR_USD | H1 | 2865 | `045bc4c8507f2ababb5e69ef4b8a82fc6ae5f4e58dd9e52c46e46ea31cf6ad61` |
| 56 | EUR_USD | H1 | 2793 | `fe440f9ad13d526181a4c123077fda25c1be1d55154bcad424c2b0a44b4e7547` |
| 57 | EUR_USD | H1 | 2849 | `ce2266b56950fa5ba3e936b5864b7e157c2022b2fe1e41944cd96979942f9586` |
| 58 | EUR_USD | H1 | 2848 | `8f5088997ac5f8bc9545c68428b92a4ef46ad39279dacb18b5e842f181cc7260` |
| 59 | EUR_USD | H1 | 2817 | `04b4d18e9f2ff9fe5afff90acfb30d933a4477f09722c36a8714d0290e45e15a` |
| 60 | EUR_USD | H1 | 2874 | `ab1f34460aec46feb2e821e12843d64f258e66b54b25156114a177fd5022758f` |
| 61 | EUR_USD | H1 | 2798 | `c21bffe7c0fa56de4f2e6b9d624c29ebc907dd5d5763d74770662af90d42d7ed` |
| 62 | EUR_USD | H1 | 2848 | `fe395337a13e26dd34d5e9a9ad10e27bcaf2188467d7cda28b0b607ee3f261b7` |
| 63 | EUR_USD | H1 | 2802 | `b62e50641f1fb6e5f87eb5a8b1acfc3be25b149bb135530ca71926bfd2135ecd` |
| 64 | EUR_USD | H1 | 2862 | `83cc638b7cf0fb59e2d306e50ee75b8f5a00471cc5c6c168878b7057aea8ebcb` |
| 65 | EUR_USD | H1 | 2040 | `f82b18d92fffe7e59a4996f4f202a48b1f4ba2af493ef1456dcdf43c35c8580b` |
| 66 | EUR_USD | W | 471 | `21ad56462afcd85822a8efe9100b1edfb8bce68ab0c8e4d4e3b635faba0f8f6d` |
| 67 | GBP_USD | D | 2902 | `17a326a0c7190098c36637377976c5b54c01cb447c99a6b0b3c75c81ae21d0d3` |
| 68 | GBP_USD | H1 | 2938 | `f6b374cfde8e34a57fcef57450c2b96fe064a75b64ec7a5e84fa11f9e75f99fa` |
| 69 | GBP_USD | H1 | 2952 | `12ddf7ba3cd25ba294f168993b92d3584f67cd84a8b188b67b5126fc4d0a7c0e` |
| 70 | GBP_USD | H1 | 3287 | `b9d7b361833e59228a9d34615c06e0af01f6913f6b54875d6378d5e4bea972ae` |
| 71 | GBP_USD | H1 | 3443 | `086f1b6839d90f4468074ee974fcbb1a3784402174b71340ce1f4a154ac7c887` |
| 72 | GBP_USD | H1 | 2984 | `6608be93d6b0943d8237ff8bc9f857fa02b2765cab66c833e008579cbde7faa9` |
| 73 | GBP_USD | H1 | 2934 | `960cafd056314e91f4d5c59e74cddb12eed5bc6d291749a5dfba79fbeef2dfa3` |
| 74 | GBP_USD | H1 | 2831 | `07567b26c88f663221fad95134ef7de1b3beb1bac791c56a1b41fbb9c814b7f5` |
| 75 | GBP_USD | H1 | 2849 | `7127f73a5fc171d9f192f2f2877dd0e6760cef4f2f7954933060819e2e84415d` |
| 76 | GBP_USD | H1 | 2825 | `842e7ae7682e605dace7445a5ef5973be0b0ae139be6e576385b68e651028e91` |
| 77 | GBP_USD | H1 | 2865 | `118b2b300d66ed9af4385cc42c89a674f8ee897a6f35b50fbafe04eb319ce663` |
| 78 | GBP_USD | H1 | 2793 | `d91ff07e70d3acd54f5fa5705343e849303053d4621990a71731f595c025089b` |
| 79 | GBP_USD | H1 | 2849 | `c4d71e4d6cd8b14faff12de3ca1a543b9779e8b2cf9f3e34d3ab962a38837030` |
| 80 | GBP_USD | H1 | 2848 | `a509a9ee12a15684107a7b8d891ff15556af40f9161e22310039026ae589dbf8` |
| 81 | GBP_USD | H1 | 2817 | `7eb0517ec653c261f7e52cc0a29f501f13e115f863fb48c406f35274d6e0d1d7` |
| 82 | GBP_USD | H1 | 2874 | `bcc3e1320fe0f3155b21f8d50f650054daab8ad5efb2ab6acd03521f14a5ae8b` |
| 83 | GBP_USD | H1 | 2798 | `bf4c91672d43cb7a86e29194743223635045f6672b742a3f7f69eaaf5cded8ff` |
| 84 | GBP_USD | H1 | 2848 | `a1e298d1682838b1dade8eef3dd3f735a1b5c35ccaf49f7f517a7c3a3c2c3b75` |
| 85 | GBP_USD | H1 | 2802 | `14ecc9014eb643cb783d2699c048607b64d9a50986c51985153d9d48a2949a5f` |
| 86 | GBP_USD | H1 | 2862 | `5db0c034e12b7e7296030ee13c25a8cb1e341819954358aae12c5a9c4408a51c` |
| 87 | GBP_USD | H1 | 2040 | `8f602cb551764599a6e9153860347c4b36662f949085e59ce7bb834277e03f5a` |
| 88 | GBP_USD | W | 471 | `ea2ff497fb2cb863d3f486547f09bef10bdc90fbb4c7dcd0a0150b183c1ef922` |
| 89 | USD_CAD | D | 2894 | `6440add14e445da10f833e2753d0f1a830e5242ebd09947725988a0198b2c248` |
| 90 | USD_CAD | H1 | 2923 | `d7c4c26f77847c93ffbed973f6cc98ca79d2de54617011f1b6d487c6a5e798f0` |
| 91 | USD_CAD | H1 | 2943 | `d4affa9cf4893d7781997a6d7ad1f8bab2e5112d28c2caa45e66b94074360fd5` |
| 92 | USD_CAD | H1 | 3287 | `819db211a27460e5323eeda6f52fe7028e56ed916c9bf62ca1416d4bc3aea0bc` |
| 93 | USD_CAD | H1 | 3441 | `e65ae98a3b67b5e045b488ecf650f42ab24ca4c1d96db0b55920319601842974` |
| 94 | USD_CAD | H1 | 2980 | `6a6d27e594991de9ce89107894646eb74df68dd4ac7fb2a6ba55ff71c3902284` |
| 95 | USD_CAD | H1 | 2927 | `f7a31b6ac5eac26c7734522bd3e001bcf3a1f991871e8db7df1792f247fa3ead` |
| 96 | USD_CAD | H1 | 2832 | `70eb8eb5af3030c34e2aceb56fc3411261380800849729e07a2f9075bf5fae8f` |
| 97 | USD_CAD | H1 | 2850 | `9a20bc668c1bf0a4f894a66d6f43edb0c89f72c51fa6b3b784c580a0f1e9b211` |
| 98 | USD_CAD | H1 | 2825 | `4eb56bf68309ed5f25ac8f4a73bd5d47db5d7cde1362e4767f705f7d8fc0894b` |
| 99 | USD_CAD | H1 | 2864 | `c6df46d6fb598a7b2729337e5be9af500635a32e079d2b4e53562bfae0f8f70f` |
| 100 | USD_CAD | H1 | 2793 | `576e1e753618169e667f1a0ec2d19342ac34fab642b14f6075c0b3a858be7b4c` |
| 101 | USD_CAD | H1 | 2849 | `071453d0289f6712c91c486e1002d2a0eccdea10a22a96722aa2405970ed2375` |
| 102 | USD_CAD | H1 | 2848 | `d7434e322d95c35cc7ed36b81b573596ccc211cdf79ee068eb480cb28d878168` |
| 103 | USD_CAD | H1 | 2817 | `e7cfb564d40ea357fd0e478876436cff0a836d56a421cdc5ba418cd976d79768` |
| 104 | USD_CAD | H1 | 2874 | `306e2eff6287bbfd800ce06821ab95b17fd6d31c84e2400364c2a2def96581b9` |
| 105 | USD_CAD | H1 | 2798 | `6e89f6ac757f53ae614eb51d76e4efc84b880dbf7cb8b0dc1e20f88d28a5fa95` |
| 106 | USD_CAD | H1 | 2848 | `4318d1aeef37a70da41fe2d92b17258e4ad79529befeed9340b79c16b5d1c466` |
| 107 | USD_CAD | H1 | 2802 | `5cd2a1478adc502f4438f17835bd69e05dc92cb5c25778ba4fe5d7d628684783` |
| 108 | USD_CAD | H1 | 2862 | `79560473eaf6d2448a4a67bddb3d99e02a13ea4f6813a4748d5b7ca2c8d48c5b` |
| 109 | USD_CAD | H1 | 2042 | `c4997709d9e2f17f5ccb2ef8291d4e268f79e4133ff73b4bc054461df57d8435` |
| 110 | USD_CAD | W | 471 | `213d30a1582a247ddb240f6476e52c5ff4f2b400a2a39bb4027f5640e4767927` |
| 111 | USD_JPY | D | 2907 | `7f7178617f2e1d6003930ed2330824b3b416e6ecedd7790cc89d7d8835113e9a` |
| 112 | USD_JPY | H1 | 2931 | `249676de5a58908ccce30dec31e2bc0b7ed8066c2701016bd0d52a4e2f4af11b` |
| 113 | USD_JPY | H1 | 2952 | `3bbc69447da9b2e9cf1623992b611c70c2ec51bb8b699f20198ccacd7d0027b5` |
| 114 | USD_JPY | H1 | 3292 | `913a8d32dae61534db14c04213add198d3bf3bb5c7dd5ae859067a763cacbae6` |
| 115 | USD_JPY | H1 | 3443 | `2f708fb1fb88e3ea46918e9b8104f7dab458ba6988339bf2578434e422532956` |
| 116 | USD_JPY | H1 | 2985 | `29b11a044672d8c778212042e403e14922e7aa7fb877711ee58147bb0a260e1b` |
| 117 | USD_JPY | H1 | 2939 | `fce6794dbc7f6a1b87695c98dc2aa5fcb2aa2569e26a765c31eecd429577ed18` |
| 118 | USD_JPY | H1 | 2832 | `4b502904eadd58344ce8af629e94894bd94d4efa63195ef063292a821abb191c` |
| 119 | USD_JPY | H1 | 2850 | `3bfe72226e49b2ded5810255a28859d4be6d371e773eb835c29378f8dfb45e5e` |
| 120 | USD_JPY | H1 | 2825 | `5781c5576bd730de089fd024d47e66978b36a3e4f28c6d788df318469d0bec32` |
| 121 | USD_JPY | H1 | 2865 | `a3a396c88bf7d6060236e82dc9c28338fea6ff67dc913806688ac8371674e47a` |
| 122 | USD_JPY | H1 | 2793 | `7204667cccc1c925ebce3ad37ab589e20e429f2837202f8cb637573f1068608c` |
| 123 | USD_JPY | H1 | 2849 | `7a9766ace8e398c77faf08513f7ccc6b3b8a94fe02ec7baba9574aa028bd1348` |
| 124 | USD_JPY | H1 | 2848 | `041d41c4150f60c3a25df930e719c290b53dcc1748653b055ad1260f18fdc9c8` |
| 125 | USD_JPY | H1 | 2817 | `a535e059f5c6261fde1c142fba9a9827f72231db9ddc085acb3c8aaf7f942dcc` |
| 126 | USD_JPY | H1 | 2874 | `22ddf5715b4ac176f8d3ada0ff24ad537d7c8219a51a473f227cf8f0053c2475` |
| 127 | USD_JPY | H1 | 2798 | `bf9c09183fc6d48a7cebb35dc8dab366e949d1881aac87ef10ce4dc3c6f9908c` |
| 128 | USD_JPY | H1 | 2848 | `e2918b2848e9ca01c380a531a1ab7d7890a9e1742e796d23f64c9f0fbc901b68` |
| 129 | USD_JPY | H1 | 2802 | `f00c8e78cab9bd35b7f45609f2b25fb3c7365a87eaf258aefa637b802f82e4c2` |
| 130 | USD_JPY | H1 | 2862 | `282f08ed695764e3a3bd0b6477fe000b74f9cb67007905583638b554e3b8710a` |
| 131 | USD_JPY | H1 | 2041 | `a2228de06860663aa8ee8c2166db6ba866f264dad1fb42b61337aa50466a66d0` |
| 132 | USD_JPY | W | 471 | `445435f2a7c895535806850aedf056b22b316395169ec2cf795bfc99537a1d10` |
