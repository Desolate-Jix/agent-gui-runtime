# Hierarchical Region Partition MVP Input Audit

## Finding

The existing MVP model input is primarily atomic element geometry, not coarse region proposals.

`build_anonymous_candidates` reads each cleaned inventory item's bbox, rejects invalid or out-of-bounds boxes, merges only exact duplicate bboxes, and retains at most 96 boxes using spatial coverage and area priority. A candidate usually represents one OCR, UIA, parser, or vision element. The compact model payload preserves that atomic bbox and its source count; it does not add whitespace, separator, cluster-envelope, or remainder-region proposals.

## Fixed-screenshot evidence

| Sample | Inventory boxes | Model candidates | Observed limitation |
| --- | ---: | ---: | --- |
| WhatsApp | 111 | 96 | icons, avatars, text, and list-row elements dominate; the rail/list/chat panes are not supplied as coarse alternatives |
| Notepad | 15 | 15 | title/menu/status elements exist, while the large blank editor has no candidate |
| Python.org | 227 | 96 | navigation, text, cards, and rows are capped atomic boxes; major page sections are not proposed directly |

This evidence supports only the conclusion that the 8B organizer is unreliable when asked to reconstruct hierarchy from many atomic element boxes. It does not test whether 8B can adjudicate a small set of program-generated coarse proposals.
