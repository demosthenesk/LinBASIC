/* Minimal ICU common-data stub (same layout as ICU's own "stubdata" library).
 * Qt 6 only needs ICU for collation and legacy codecs; LinBASIC uses neither, so the
 * 31 MB data library is replaced by an empty table to keep the AppImage small. */
#include <stdint.h>
typedef struct {
    uint16_t size, reservedWord;
    uint8_t isBigEndian, charsetFamily, sizeofUChar, reservedByte;
    uint8_t dataFormat[4], formatVersion[4], dataVersion[4];
} UDataInfo;
typedef struct {
    uint16_t headerSize;
    uint8_t magic1, magic2;
    UDataInfo info;
    char padding[8];
    uint32_t count, reserved;
    struct { uint32_t nameOffset, dataOffset; } toc[1];
} ICU_Data_Header;
__attribute__((visibility("default"))) const ICU_Data_Header icudt73_dat = {
    32, 0xda, 0x27,
    { sizeof(UDataInfo), 0, 0, 0, 2, 0, { 0x43, 0x6d, 0x6e, 0x44 }, { 1, 0, 0, 0 }, { 0, 0, 0, 0 } },
    { 0, 0, 0, 0, 0, 0, 0, 0 }, 0, 0, { { 0, 0 } }
};
