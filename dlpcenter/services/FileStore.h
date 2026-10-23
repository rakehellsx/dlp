#pragma once
#include <string>
namespace dlp {
std::string readStoredFile(const std::string &relative);
void storeFile(const std::string &relative, const std::string &bytes);
} // namespace dlp
