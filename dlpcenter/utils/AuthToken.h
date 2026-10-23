#pragma once
#include <drogon/drogon.h>
#include <regex>
inline std::string requestToken(const drogon::HttpRequestPtr &req) {
    auto auth = req->getHeader("Authorization");
    if (!auth.empty())
        return auth.rfind("Bearer ", 0) == 0 ? auth.substr(7) : "";
    return req->getCookie("dlp_token");
}
inline bool validTokenFormat(const std::string &token) {
    return std::regex_match(token, std::regex("[a-f0-9]{64}"));
}
inline bool validCookieRequest(const drogon::HttpRequestPtr &req) {
    return req->method() == drogon::Get || !req->getHeader("Authorization").empty() ||
           req->getHeader("X-DLP-Request") == "1";
}
