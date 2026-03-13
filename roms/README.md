# Reference ROMs

Place verified stock EPROM dumps here as `.bin` files.

| File | ECU Part | Variant | SHA256 |
|------|----------|---------|--------|
| `893906266D_stock.bin` | 893906266D | 7A Late | TBD |
| `893906266B_stock.bin` | 893906266B | 7A Early | TBD |
| `4A0906266_stock.bin`  | 4A0906266  | AAH 12v  | TBD |

Once you add a verified stock dump, update the `known_hashes` list in
`hachirom/roms.py` with its SHA256 so HachiROM can auto-detect it.

To get the SHA256 of a file:
```
# Windows
certutil -hashfile my_rom.bin SHA256

# Linux / macOS
sha256sum my_rom.bin
```
