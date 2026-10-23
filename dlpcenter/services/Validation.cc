#include "Validation.h"
#include <stdexcept>
#include <set>
#include <regex>
#include <cmath>
#include "utils/Platform.h"
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#endif
#include <ctime>
#include <iomanip>
#include <sstream>
#include <algorithm>
#include <vector>
namespace dlp {
static void require(bool ok, const std::string &message) {
    if (!ok)
        throw std::invalid_argument(message);
}
static size_t chars(const std::string &s) {
    size_t n = 0;
    for (unsigned char c : s)
        if ((c & 0xc0) != 0x80)
            ++n;
    return n;
}
std::string text(const Json::Value &v, const std::string &key, const std::string &fallback,
                 size_t limit) {
    auto x = v.get(key, fallback);
    require(x.isString(), key + " 必须为文本");
    auto s = x.asString();
    require(s.find('\0') == std::string::npos, "文本不能包含空字符");
    auto a = s.find_first_not_of(" \r\n\t"), b = s.find_last_not_of(" \r\n\t");
    s = a == std::string::npos ? "" : s.substr(a, b - a + 1);
    require(chars(s) <= limit, key + " 内容过长");
    return s;
}
static std::string option(const Json::Value &v, const std::string &key, const std::string &fallback,
                          const std::set<std::string> &values) {
    auto s = text(v, key, fallback);
    require(values.count(s), key + " 选项无效");
    return s;
}
static int integer(const Json::Value &v, const std::string &key, int fallback, int low, int high) {
    auto x = v.get(key, fallback);
    require(x.isNumeric() && !x.isBool() && std::isfinite(x.asDouble()) &&
                x.asDouble() == std::floor(x.asDouble()) && x.asDouble() >= low &&
                x.asDouble() <= high,
            key + " 取值无效");
    return x.asInt();
}
static bool boolean(const Json::Value &v, const std::string &key, bool fallback) {
    auto x = v.get(key, fallback);
    require(x.isBool(), key + " 必须为布尔值");
    return x.asBool();
}
Json::Value watermark(const Json::Value &v) {
    require(v.isObject(), "无效的水印配置");
    Json::Value r;
    r["name"] = text(v, "name", "", 80);
    r["content"] = text(v, "content", "", 240);
    require(!r["name"].asString().empty() && !r["content"].asString().empty(),
            "水印名称和内容不能为空");
    auto content = r["content"].asString();
    require(std::count(content.begin(), content.end(), '\n') <= 3, "水印最多4行文本");
    std::regex token("\\{([^{}]+)\\}");
    std::set<std::string> tokens = {"企业名称", "姓名",   "账号", "部门",
                                    "终端",     "终端IP", "时间", "文档名称"};
    for (auto it = std::sregex_iterator(content.begin(), content.end(), token);
         it != std::sregex_iterator(); ++it)
        require(tokens.count((*it)[1]), "水印内容包含不支持的动态字段");
    r["type"] = option(v, "type", "screen", {"print", "screen", "screenshot"});
    r["scope"] = text(v, "scope", "全体终端", 80);
    r["condition"] = option(v, "condition", "always", {"always", "sensitive", "apps"});
    r["fontFamily"] =
        option(v, "fontFamily", "Microsoft YaHei", {"Microsoft YaHei", "SimSun", "Arial"});
    r["position"] = option(v, "position", "tile", {"tile", "center", "top", "bottom"});
    r["paperSize"] = option(v, "paperSize", "A4", {"A4", "A3"});
    r["screenTarget"] = option(v, "screenTarget", "all", {"all", "primary"});
    r["fontSize"] = integer(v, "fontSize", 20, 12, 48);
    r["opacity"] = integer(v, "opacity", 18, 5, 80);
    r["angle"] = integer(v, "angle", -30, -90, 90);
    r["spacing"] = integer(v, "spacing", 180, 100, 360);
    r["priority"] = integer(v, "priority", 10, 1, 999);
    r["color"] = text(v, "color", "#66737f");
    require(std::regex_match(r["color"].asString(), std::regex("#[a-fA-F0-9]{6}")), "水印颜色无效");
    r["enabled"] = boolean(v, "enabled", true);
    r["bold"] = boolean(v, "bold", false);
    r["bothSides"] = boolean(v, "bothSides", true);
    for (auto key : {"apps", "screenshotMethods"}) {
        Json::Value defaults(Json::arrayValue);
        if (std::string(key) == "screenshotMethods")
            for (auto x : {"system", "tools", "clipboard"})
                defaults.append(x);
        auto value = v.get(key, defaults);
        require(value.isArray() && value.size() <= 5, "应用或截屏方式配置无效");
        std::set<std::string> allowed =
                                  std::string(key) == "apps"
                                      ? std::set<std::string>{"Office 文档", "PDF 阅读器", "浏览器",
                                                              "即时通讯", "其他应用"}
                                      : std::set<std::string>{"system", "tools", "clipboard"},
                              seen;
        r[key] = Json::Value(Json::arrayValue);
        for (const auto &x : value) {
            require(x.isString() && allowed.count(x.asString()), "应用或截屏方式配置无效");
            if (seen.insert(x.asString()).second)
                r[key].append(x);
        }
    }
    require(r["condition"] != "apps" || !r["apps"].empty(), "请至少选择一个适用应用");
    require(r["type"] != "screenshot" || !r["screenshotMethods"].empty(), "请至少选择一种截屏方式");
    r["printers"] = text(v, "printers", "全部打印机", 200);
    require(!r["printers"].asString().empty(), "请填写打印机范围");
    r["description"] = text(v, "description", "", 240);
    auto id = text(v, "id");
    if (!id.empty()) {
        require(std::regex_match(id, std::regex("WM-[A-Z0-9-]{1,60}")), "水印策略编号无效");
        r["id"] = id;
    }
    return r;
}
Json::Value metadata(const Json::Value &v) {
    require(v.isObject(), "无效的图片关联信息");
    Json::Value r;
    for (const auto &pair : std::vector<std::pair<std::string, int>>{{"title", 100},
                                                                     {"code", 128},
                                                                     {"user", 80},
                                                                     {"department", 80},
                                                                     {"endpoint", 120},
                                                                     {"endpointUid", 36},
                                                                     {"ip", 45},
                                                                     {"time", 40},
                                                                     {"policyId", 80},
                                                                     {"content", 4000},
                                                                     {"note", 1000}})
        r[pair.first] = text(v, pair.first, "", pair.second);
    require(!r["title"].asString().empty(), "请填写图片标题");
    auto uid = r["endpointUid"].asString();
    require(
        uid.empty() ||
            std::regex_match(uid, std::regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")),
        "终端唯一标识格式无效");
    r["type"] = option(v, "type", "unknown", {"unknown", "print", "screen", "screenshot"});
    r["status"] = option(v, "status", "pending", {"pending", "reviewed"});
    if (!r["ip"].asString().empty()) {
        char out[INET6_ADDRSTRLEN];
        unsigned char bytes[16];
        auto ip = r["ip"].asString();
        int family = ip.find(':') == std::string::npos ? AF_INET : AF_INET6;
        require(inet_pton(family, ip.c_str(), bytes) == 1, "终端 IP 地址无效");
        inet_ntop(family, bytes, out, sizeof out);
        r["ip"] = out;
    }
    if (!r["time"].asString().empty()) {
        auto s = r["time"].asString();
        std::smatch m;
        require(
            std::regex_match(
                s, m,
                std::regex("([0-9]{4})-([0-9]{2})-([0-9]{2})[ "
                           "T]([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?(Z|[+-][0-9]{2}:[0-9]{2})?")),
            "水印时间格式无效");
        int yr = std::stoi(m[1]), mo = std::stoi(m[2]), day = std::stoi(m[3]), h = std::stoi(m[4]),
            min = std::stoi(m[5]), sec = m[6].matched ? std::stoi(m[6]) : 0;
        require(mo >= 1 && mo <= 12 && day >= 1 && day <= 31 && h <= 23 && min <= 59 && sec <= 59,
                "水印时间无效");
        std::tm tm{};
        tm.tm_year = yr - 1900;
        tm.tm_mon = mo - 1;
        tm.tm_mday = day;
        tm.tm_hour = h;
        tm.tm_min = min;
        tm.tm_sec = sec;
        auto seconds = makeUtcTime(tm);
        require(tm.tm_year == yr - 1900 && tm.tm_mon == mo - 1 && tm.tm_mday == day,
                "水印日期无效");
        if (m[7].matched) {
            auto zone = m[7].str();
            int offset = 0;
            if (zone != "Z") {
                auto zh = std::stoi(zone.substr(1, 2)), zm = std::stoi(zone.substr(4, 2));
                require(zh <= 23 && zm <= 59, "时区无效");
                offset = (zh * 60 + zm) * 60 * (zone[0] == '-' ? -1 : 1);
            }
            seconds += 8 * 3600 - offset;
            tm = utcTime(seconds);
        }
        std::ostringstream out;
        out << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
        r["time"] = out.str();
    }
    return r;
}
} // namespace dlp
