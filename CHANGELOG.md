# Changelog

## [0.2.0](https://github.com/GSA-TTS/agentic-coding-maintainers/compare/v0.1.0...v0.2.0) (2026-11-07)


### Features

* **orchestration:** pilot cooperative session-bound lifecycle ([#128](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/128)) ([aeaa68c](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/aeaa68ce36ab515d76640205326be0e4df8142ad))
* **orchestration:** recover interrupted bound tasks explicitly ([#133](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/133)) ([6a63c14](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/6a63c14c40d9770826c7d2687c400811f2957901))
* **tools:** support pinned Linux ARM64 CI tool installation ([#131](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/131)) ([90a4861](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/90a4861e59a9b5b8ef122253238bdc6f977117ba))


### Bug Fixes

* **cleanup:** preserve rename safety on overlayfs ([#134](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/134)) ([568125c](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/568125c3d33572eb64d681b857439d81c10adbe7))

## 0.1.0 (2026-11-06)


### Features

* add cross-repository maintainer tooling ([ff91efa](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/ff91efa58b3d53a295730a275c51b3dd823024a4))
* **cross-repo-epic:** read the portfolio from config, not constants ([#17](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/17)) ([09fe89c](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/09fe89c2b48954bf37f691fd3b48188face3073f))
* **delivery:** apply collected owner repairs with durable recovery ([#99](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/99)) ([be5b8ad](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/be5b8adaad13e9c6359e09b8d4858b0ee48ba726))
* **delivery:** assign and admit prepared review attempts ([#102](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/102)) ([426e3ec](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/426e3ec5733cfb2243fe80272511ebeba9037b78))
* **delivery:** compose admitted owner proposal handoffs ([#98](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/98)) ([87a4492](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/87a44921fce99d2a583b28832ed836121c6afc3d))
* **delivery:** compose bounded foreground review handoffs ([#96](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/96)) ([6648575](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/6648575a5c71baef7ce1d5711ad43bab79c57e9d))
* **delivery:** prepare authenticated fresh review after repair ([#101](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/101)) ([4edeb53](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/4edeb533c23d556f3c214c52b5a71228ed5aa158))
* **delivery:** report human-approved PR batches safely ([#86](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/86)) ([db8fe37](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/db8fe37d1cd8b09db1358759535ccee8e430592a))
* **delivery:** verify and adopt exact owner repair commits ([#100](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/100)) ([373c0af](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/373c0afe21288ce9fb9c8fccc2baaef41f8cc9dd))
* **epics:** surface issues with sub-issues as candidates ([#39](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/39)) ([68dffbf](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/68dffbfb63728b48f2c8b5421f737a05268d3c8e))
* **evaluation:** adapt private Issues captures without completeness credit ([#58](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/58)) ([b898e17](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b898e17840e3a80635b5758e6d31a98d64d4a40b))
* **evaluation:** add honest current-state workflow scorecard ([#20](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/20)) ([38a0145](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/38a01457f4736eee342da2e416f471dddc6cd235))
* **evaluation:** append validated private cohort events ([#27](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/27)) ([67d18e0](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/67d18e012029d1eef5d455c1f9a9df66addf0531))
* **evaluation:** bind shadow replay to a private cohort manifest ([#54](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/54)) ([0698ccb](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/0698ccb7a4eb380f4b41bd1fcd4db96fc3b81168))
* **evaluation:** capture private full-terminal Issues observations ([#59](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/59)) ([a18bc01](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/a18bc01a10c96f7e967994d1ac792a8fe7c1a1ce))
* **evaluation:** check merge observation against private intake ledger ([#49](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/49)) ([ba47772](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/ba47772f070c6e1fd7fe9ea6eb27ae47bd0e332d))
* **evaluation:** classify supplied PR merge evidence without delivery credit ([#46](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/46)) ([f6a08d7](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/f6a08d7d7b7326d2433eb4851a2d2a517de59de9))
* **evaluation:** flag unknown cases for maintainer disposition ([#35](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/35)) ([b74e463](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b74e463bc3ed9376a5b84b58c4704f3334118e39))
* **evaluation:** observe bound PR merges with GET-only GitHub reads ([#47](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/47)) ([fd3c254](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/fd3c254ff30fe79e0412d76d8e7f238ffaedf6bb))
* **evaluation:** observe bounded GitHub Issues connection twice ([#56](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/56)) ([a678fc5](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/a678fc5d715fcda8e33b9fceb38b6678bfeb5a07))
* **evaluation:** observe historical review requests for one PR ([#60](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/60)) ([7485c68](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/7485c686d70a871c73ab0db3101ae70a9da8a200))
* **evaluation:** pilot read-only sanitized cohort reflection ([#26](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/26)) ([b77f72f](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b77f72f8f13e8a6e365b6d248c66754906e43684))
* **evaluation:** preserve eligibility decisions as correction events ([#37](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/37)) ([11d6da4](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/11d6da4a97f23552de0518d8c87fd3a69ac3eaab))
* **evaluation:** reconcile intake with independently captured request inventory ([#28](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/28)) ([128350e](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/128350e43cfb832d71c7d932eb2b4561bb33d070))
* **evaluation:** record agent case-to-PR associations without credit ([#50](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/50)) ([ff031f0](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/ff031f087a95619365aa880dcf6011fea138f80d))
* **evaluation:** replay shadow exception recommendations against labels ([#53](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/53)) ([3bf61e5](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/3bf61e5103f101ea7147077e168b1b41622a629e))
* **evaluation:** report correction quality with fixed intake denominator ([#38](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/38)) ([4d8543e](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/4d8543e8b60aa3d3e952b98b3256d1b867b5dc02))
* **evaluation:** validate independently declared source page chains ([#55](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/55)) ([2c59740](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/2c59740a2ebb9d37d24bfe40018d34f16aff3ff8))
* **execution:** freeze required cases and assess current obligations ([#80](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/80)) ([3a38671](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/3a386713d879d64f6b6df48bd6b7b87f60054657))
* **execution:** observe isolated black-box assertions ([#79](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/79)) ([9b3dd2f](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/9b3dd2f7dd175d111666a2b1e66026586963892b))
* **maintainers:** operate self-contained maintainer work ([#18](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/18)) ([a270277](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/a2702770f083db95e8a665819cfacdc37286af4c))
* **monitor:** retain durable PR observations and coverage ([#83](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/83)) ([70659a6](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/70659a6fc97280625b6470cb4ad5fa1cf18bacdc))
* **orchestration:** add offline shadow exception-recovery planner ([#51](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/51)) ([929725d](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/929725dbce6087a625ff0618eff8cf54970d0eed))
* **orchestration:** add reusable workspace coordinator ([#4](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/4)) ([ce3d120](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/ce3d120fda9c937417b4c47564e734f4a38ae371))
* **orchestration:** derive shadow diagnostic budget from private attempts ([#52](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/52)) ([98bf82f](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/98bf82fe7f8244af81d52163478ab16917a92de1))
* **orchestration:** inspect retained ownership at explicit authority root ([#122](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/122)) ([f21052d](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/f21052d6097cd40164d7f7c42a0e6f7bf361701b))
* **portability:** add read-only workspace upgrade preflight ([#95](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/95)) ([1322976](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/132297676ad58d15cdbc6224bf3d82410721a91e))
* **qualification:** measure isolated OpenCode profile policy ([#108](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/108)) ([b38f2f9](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b38f2f98ba29425125ebc6d4515e90b92447be71))
* **qualification:** qualify actual tool dispatch enforcement offline ([#109](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/109)) ([12c73f4](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/12c73f49e621b2754448e99e88579dd32978303e))
* **reconciliation:** bind observed candidates to existing review tasks ([#84](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/84)) ([2dc04ad](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/2dc04add6bc4bef009eabe5dc343acb783285b47))
* **release:** establish semver lifecycle and MSB delivery plan ([#126](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/126)) ([65a1366](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/65a13669cb340398021b11bc6f0a33478072e67c))
* **repair:** apply bounded original-owner replacements ([#81](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/81)) ([05bc35d](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/05bc35d216d631749de089003894e517406b4feb))
* **review:** accept structured collected review claims ([#78](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/78)) ([71b6048](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/71b604888e2a35242d602ca1b1479f85133ca483))
* **review:** classify offline PR review eligibility ([#113](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/113)) ([b98d9e1](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b98d9e13de7c5e3fcd1c09d50bc83fcb3fd92bf9))
* **review:** collect assignment-bound runtime observations ([#77](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/77)) ([23cf6c5](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/23cf6c5f6de847d33e3e63ef3fc9c3f89c163383))
* **review:** evidence-bound source review foundation ([#76](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/76)) ([b4d3e8a](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b4d3e8ad48f3a7fe9b328ad617f60af79b1cd47e))
* **review:** export isolated reviewer inputs with source provenance ([#104](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/104)) ([8220b10](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/8220b10c8f5039f0fb43e15b2df943d0defbf37a))
* **review:** reserve admission-bound reviewer destinations ([#106](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/106)) ([0f0417b](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/0f0417bd53d1adc55024cc7439b4d3867a4b1077))
* **skill:** Add evidence-bound federal authority research workflow ([#114](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/114)) ([6166a8e](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/6166a8e00c6443c775780a0af99154e5bb4ec5a7))
* **skills:** verify OpenCode 2 compatibility ([#13](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/13)) ([8aa456d](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/8aa456d30835d4134355cc9c917393bad4b75ad3))
* **workflow:** integrate real review and owner repair qualification ([#82](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/82)) ([1f83547](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/1f83547cd300ef63e9de8dc3920e4626c46b59f7))
* **workspace:** unify cleanup and sync disposal under tmp ([#121](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/121)) ([0a4397f](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/0a4397fe5b75d8411af372bac07a55d457bcd8d3))


### Bug Fixes

* **ci:** support hosted repository checks ([2e6e800](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/2e6e80012244c501469e114e6f298da473a25754))
* **delivery:** surface requested review changes in batch reports ([#89](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/89)) ([6284fee](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/6284fee097083155abda8f36a0eefe375ff893e6))
* **monitor:** bound transient gateway retries for read queries ([#110](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/110)) ([2f7c9d1](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/2f7c9d1faa3d66ae2313b88363cdadd2ebbc1660))
* **orchestration:** require shared authority in linked worktrees ([#123](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/123)) ([00091f9](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/00091f99cdc08eb1ba3055524ed809a07d5e739a))
* **orchestration:** reserve Claimed for claim command ([#9](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/9)) ([6527fda](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/6527fda34201c1719cd3e1fc84cd85054aeb1cca))
* **orchestrator:** accept uninitialized gitlinks ([#45](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/45)) ([5bd0665](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/5bd0665fc837a1737a37d41c5265a2e06eba8d11))
* **orchestrator:** isolate temporary Git fixtures from managed hooks ([#93](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/93)) ([7e95e47](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/7e95e4713fa7ac646f34cc2dbca3b14c76e603ed))
* **review:** reopen findings and restore review-task dispositions ([#90](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/90)) ([b535589](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/b5355890662f51948dd10de322c45a750ab364f1))
* **review:** retain current finding dispositions for human delivery ([#88](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/88)) ([835d59f](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/835d59f51782428ad326403ba50192979e18f01a))
* **runner:** bound cleanup and explicit environment inheritance ([#105](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/105)) ([dcfbb63](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/dcfbb636834fd4cd32359ba3850bdd2cc9d69f0a))
* **skills:** keep reviewed repo instructions as data and validate draft state ([#41](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/41)) ([6f943b1](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/6f943b13ba1aae4b5feae7900b0d4845b0d93836))
* **sync:** preserve prior skill trees in manifest-backed disposal ([#40](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/40)) ([d0af939](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/d0af939a037033fc3ef2c9dc8ba0c4b821f7de52))
* **test:** avoid pipefail false red and isolate version lookup ([#34](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/34)) ([e0e833f](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/e0e833faa706239f00a29eb3f36334bd0701f272))
* **test:** stage evaluator fixtures in dated disposal outbox ([#24](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/24)) ([2e75f69](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/2e75f692db99c45f223e1c1834d3738b64af4445))
* **workflow:** make synced delivery command consumer-portable ([#91](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/91)) ([1e4eb71](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/1e4eb7127ef8aadfef5ff13771f127de920b1916))


### Performance Improvements

* **tests:** remove repeated parent compilation with CI runtime RCA ([#103](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/103)) ([7cf70fe](https://github.com/GSA-TTS/agentic-coding-maintainers/commit/7cf70feabf5317cf07114668e6ef1b406ad6093a))

## Changelog

Release Please will add dated version entries after release review. There are no
historical version entries to backfill: this repository was unversioned before
this groundwork. `version.txt` initially contains `0.0.0` only as a bootstrap
sentinel, not an issued release. The intended first release is `v0.1.0`.

## Unversioned groundwork

This is a summary of the pre-release source tree, not a claim that all deployment
modes have been qualified. Git history and the imported skills' provenance
records remain the detailed source history.

- Canonical portfolio/epic reconciliation and workspace-orchestrator skills,
  including one-writer admission, foreground monitoring and recovery safeguards.
- Review, candidate-binding and evidence workflows with offline fixtures and
  documented limits; maintainer intake and workflow-evaluation tools.
- OpenCode profiles, compatibility probes and bounded qualification drivers;
  portable workspace design and state-preserving upgrade preflight.
- Federal-authority research metadata validation, workspace cleanup, and pinned
  quality/security checks.
- Release lifecycle groundwork and an MSB-first workspace qualification plan.

No MSB full-workspace qualification, Pi qualification, signed distribution
artifact, package publication, or stable 1.0 contract is implied by this summary.
