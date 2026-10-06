# GoldED+ charset findings

2026-10-06. Source review with alias follow-up; not a GoldED+ compatibility test.
Reviewed upstream `golded-plus/golded-plus` at
`1a251c6375081453a410bb8d647be120b8902de3`, the latest 150 commits and
charset/MIME code. GoldED+ was not executed and the complete history was not
compared against every local archive.

## Relevant changes

- [5a25268 — prefer CHRS/CHARSET over RFC Content-Type](https://github.com/golded-plus/golded-plus/commit/5a25268bd5495497230575be76843ff84b10ce19)
  (2026-02-20). Both libraries currently inspect CHRS/CHARSET only. Keep this
  precedence if RFC body-charset detection is introduced.
- [b806f90 — correct KOI8-R to UTF-8](https://github.com/golded-plus/golded-plus/commit/b806f9014b237d2b252c98369296eefee10a94f1)
  (2023-10-04). The conversion table had been copied from CP866. The libraries
  use Python codecs/PHP iconv, so do not copy the table. Add independent
  Cyrillic fixtures to guard against confusing these encodings.
- [a632343 — identity conversion](https://github.com/golded-plus/golded-plus/commit/a6323432a1a763df672963ba0d1b05f68dc170d2)
  (2023-11-06). Upstream prioritizes an explicit identity table before a no-op.
  Same-charset decoding must not silently choose another import encoding.
  This is an encoding invariant, not a mojibake scoring rule.
- [f6e9bf3 — prevent UUencode corruption by quote/wrap](https://github.com/golded-plus/golded-plus/commit/f6e9bf377b11134da6bb23203b99c56854d1fdd2)
  (2026-03-04). Supports treating recognizable UUencode as payload. Compare
  adversarial cases against [is_uue_line](https://github.com/golded-plus/golded-plus/blob/1a251c6375081453a410bb8d647be120b8902de3/golded3/geutil.cpp#L386),
  rather than copying C++ behavior into the repair helper.

## Concrete follow-up: historical aliases

[advanced.cfg](https://github.com/golded-plus/golded-plus/blob/1a251c6375081453a410bb8d647be120b8902de3/cfgs/config/advanced.cfg#L1497)
contains the following mappings, now supported by both libraries' charset detectors:

| Historical names | Encoding |
| --- | --- |
| CP-866, +7FIDO, +7_FIDO, FIDO7, FIDO_7, RUS | CP866 |
| KOI, KOI8, GOST, CP20866 | KOI8-R |
| WIN, WIN-1251, WINDOWS-1251, CP-1251 | CP1251 |
| KOI8-U, KOI8U, KOU, KOI-U, CP21866 | KOI8-U |
| CP1125, UKR | CP1125 |

Both libraries now test these aliases through detection and decoding, using
literal CP866, KOI8-R and CP1251 bytes with the expected Unicode `Привет`.
Python also accepts the aliases as configured fallbacks; PHP retains its existing
fallback behavior. Unknown declarations still use the configured fallback,
normally CP850. Ukrainian KOI8-U and CP1125 declarations are also supported,
with fixtures for `ҐґЄєІіЇї` that distinguish them from Russian encodings.
This change adds names to existing codecs; it does not copy GoldED+ conversion
tables or add Cyrillic mojibake scoring.

## Keep the boundaries

Upstream IBMPC defaults to CP437; these libraries use CP850. Do not change that
policy as a side effect of adding Cyrillic aliases. Upstream underscore handling
and first-encoded-word charset selection are not general normalization rules.
MIME words with different charsets must be decoded individually.

No equivalent opt-in scoring algorithm, general graphic-preservation rule or
new-control-character guard was found in the reviewed charset/MIME sources.
That statement is limited to the stated search. The libraries' repair scoring
is mainly Western European; adding Cyrillic candidate encodings needs its own
fixtures/corpus evaluation. Charset decoding and heuristic repair are separate.

## Verification and remaining work

The alias change was developed in separate red-to-green cycles for each encoding
family. Python covers all names in both declaration types, plus configured
fallback scenarios. PHP covers all aliases through detection and decoding, plus declaration
case, ordering and unchanged fallback behavior. Source mappings were checked
against the pinned `advanced.cfg` lines 1498–1504. Ukrainian fixture bytes are
checked against [Unicode's KOI8-U mapping](https://www.unicode.org/Public/MAPPINGS/VENDORS/MISC/KOI8-U.TXT)
and the [CPython CP1125 mapping](https://github.com/python/cpython/blob/3.14/Lib/encodings/cp1125.py).

The PHP CP437 decoding failure is fixed. On the tested runtime mbstring rejects
CP437 and CP1125; `Text::toUtf8()` now uses iconv for those encodings when
mbstring rejects the name. `CP437`/`IBM437` and `CP1125` are accepted without
regard to case. Other invalid encoding names still raise the original
`ValueError`; existing mbstring substitution behavior is unchanged. Fixtures
cover CP437 graphics and `¢` (CP850 would decode that byte as `ø`), Ukrainian
letters and trailing null padding. The
[Unicode CP437 table](https://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/PC/CP437.TXT)
is the reference for the CP437 fixture.

An additional comparison of all 256 byte values produced identical Unicode
through the Python and PHP public decoders for CP437, CP1125 and KOI8-U.

No GoldED+ executable compatibility run was performed. Cyrillic heuristic
repair evaluation is deferred; decoding support does not imply
that the Western European repair scorer can repair Cyrillic mojibake.
