#pragma once
#include <windows.h>
#include <cstddef>
#include <cstring>

namespace nac {
// Rename the *open object*, never a pathname that can name a replacement file.
// Caller holds GENERIC_READ|DELETE, shares READ only, through read/parse/rename.
inline bool rename_open_input(HANDLE file,const wchar_t *destination) {
    if(file==INVALID_HANDLE_VALUE||!destination)return false;
    size_t length=0;while(length<1024&&destination[length])++length;
    if(!length||length==1024)return false;
    alignas(FILE_RENAME_INFO) unsigned char buffer[sizeof(FILE_RENAME_INFO)+2048]{};
    auto *rename=reinterpret_cast<FILE_RENAME_INFO*>(buffer);
    rename->ReplaceIfExists=FALSE;rename->RootDirectory=nullptr;
    rename->FileNameLength=DWORD(length*sizeof(wchar_t));
    std::memcpy(rename->FileName,destination,rename->FileNameLength);
    return SetFileInformationByHandle(file,FileRenameInfo,rename,
        DWORD(offsetof(FILE_RENAME_INFO,FileName)+rename->FileNameLength))!=FALSE;
}
}
