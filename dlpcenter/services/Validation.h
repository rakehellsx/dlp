#pragma once
#include <json/json.h>
#include <string>
namespace dlp {
std::string text(const Json::Value &v, const std::string &key, const std::string &fallback = "",
                 size_t limit = 4000);
Json::Value watermark(const Json::Value &v);
Json::Value metadata(const Json::Value &v);
} // namespace dlp
