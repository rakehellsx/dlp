#include "DlpController.h"
#include "services/Pg.h"
#include "services/Validation.h"
#include "services/ImageWorker.h"
#include "services/WorkerPool.h"
#include "utils/ApiResponse.h"
#include "utils/AuditLog.h"
#include <algorithm>
#include <set>
#include <map>
#include <regex>
#include <iomanip>
using namespace drogon;
using namespace dlp;
namespace {
const std::set<std::string> kinds = {"events",     "endpoints",      "policies", "rules",
                                     "assets",     "approvals",      "scans",    "reports",
                                     "watermarks", "watermarkImages"};
const std::set<std::string> scopes = {"全体终端",   "研发中心",   "市场营销部", "财务部",
                                      "人力资源部", "产品设计部", "行政管理部"};
void require(bool ok, const std::string &message) {
    if (!ok)
        throw std::invalid_argument(message);
}
void merge(Json::Value &target, const Json::Value &source) {
    for (const auto &key : source.getMemberNames())
        target[key] = source[key];
}
Json::Value audits(Pg &db, int limit = 500) {
    auto r = db.query(
        "SELECT id, to_char(created_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD HH24:MI:SS') AS "
        "time,coalesce(operator_name,'未登录') AS actor,action,target,detail,ip,success FROM "
        "operation_logs ORDER BY id DESC LIMIT $1",
        {std::to_string(limit)});
    Json::Value rows(Json::arrayValue);
    for (int i = 0; i < r.size(); i++) {
        Json::Value v;
        v["id"] = Json::Int64(std::stoll(r.get(i, "id")));
        for (auto key : {"time", "actor", "action", "target", "detail", "ip"})
            v[key] = r.get(i, key);
        v["success"] = r.get(i, "success") == "t";
        rows.append(v);
    }
    return rows;
}
HttpResponsePtr raw(const std::string &body, const std::string &mime,
                    const std::string &filename = "") {
    auto res = HttpResponse::newHttpResponse();
    res->setBody(body);
    res->setContentTypeString(mime);
    res->addHeader("Cache-Control", "no-store");
    res->addHeader("X-Content-Type-Options", "nosniff");
    res->addHeader("X-Err-Code", "0");
    if (!filename.empty())
        res->addHeader("Content-Disposition", "attachment; filename=\"" + filename + "\"");
    return res;
}
std::string csvCell(std::string s) {
    if (!s.empty() && std::string("=+-@\t\r").find(s[0]) != std::string::npos)
        s = "'" + s;
    std::string escaped = "\"";
    for (auto c : s) {
        if (c == '"')
            escaped += '"';
        escaped += c;
    }
    return escaped + '"';
}
void policyExists(Pg &db, const Json::Value &metadata) {
    auto id = metadata["policyId"].asString();
    require(id.empty() || !db.get("watermarks", id).isNull(), "关联水印策略不存在，请重新选择");
}
Json::Value capabilities() {
    static const Json::Value value = []() {
        Json::Value p;
        p["action"] = "capabilities";
        return imageWorker(p);
    }();
    return value;
}
HttpResponsePtr dispatch(const HttpRequestPtr &req, const std::string &imageId) {
    Pg db;
    const auto path = req->path();
    const auto actor = path == "/health" ? 0 : req->attributes()->get<int>("userId");
    auto ip = clientIp(req);
    if (path == "/health") {
        db.query("SELECT 1");
        Json::Value v;
        v["status"] = "ok";
        v["product"] = "Sentinel DLP";
        v["backend"] = "dlpcenter/Drogon";
        v["database"] = "PostgreSQL";
        v["mode"] = "prototype";
        return ApiResponse::ok(v);
    }
    if (!imageId.empty()) {
        require(std::regex_match(imageId, std::regex("WIMG-[A-F0-9]{12}")), "图片编号无效");
        auto r = db.query("SELECT encode(original,'base64') AS original,encode(thumbnail,'base64') "
                          "AS thumbnail,mime FROM dlp_watermark_images WHERE id=$1",
                          {imageId});
        require(r.size(), "图片不存在或已删除");
        bool thumb = req->getParameter("thumb") == "1",
             download = req->getParameter("download") == "1";
        auto encoded = r.get(0, thumb ? "thumbnail" : "original");
        encoded.erase(std::remove(encoded.begin(), encoded.end(), '\n'), encoded.end());
        auto mime = r.get(0, "mime");
        auto bytes = utils::base64Decode(encoded);
        std::string filename;
        if (download && !thumb) {
            db.audit(actor, "下载水印原图", imageId, "", ip);
            filename = imageId + (mime == "image/png"    ? ".png"
                                  : mime == "image/webp" ? ".webp"
                                                         : ".jpg");
        }
        return raw(bytes, thumb ? "image/jpeg" : mime, filename);
    }
    if (path == "/api/bootstrap") {
        Json::Value data;
        for (const auto &kind : kinds)
            data[kind] = db.items(kind);
        // Serialize progress updates with task creation and preserve the original 20-second demo
        // duration.
        db.begin();
        db.query("SELECT pg_advisory_xact_lock(728113)");
        auto scans = db.items("scans");
        for (auto &task : scans)
            if (task["status"] == "running") {
                auto progress = std::clamp(
                    static_cast<int>((std::time(nullptr) - task["createdAt"].asDouble()) * 5), 0,
                    100);
                task["progress"] = progress;
                if (progress >= 100) {
                    task["status"] = "completed";
                    int found = 0;
                    for (const auto &a : data["assets"])
                        if (task["scope"] == "全体终端" || a["department"] == task["scope"])
                            found++;
                    task["found"] = found;
                }
                db.put("scans", task);
            }
        db.commit();
        data["scans"] = scans;
        data["audit"] = audits(db);
        auto settings = db.query("SELECT data::text FROM dlp_settings WHERE id=1");
        require(settings.size(), "请先初始化 PostgreSQL 业务数据");
        data["settings"] = parse(settings.get(0, "data"));
        auto user =
            db.query("SELECT username,role FROM users WHERE id=$1", {std::to_string(actor)});
        require(user.size(), "用户不存在");
        data["user"]["username"] = user.get(0, "username");
        data["user"]["name"] = user.get(0, "username");
        data["user"]["role"] = user.get(0, "role");
        data["serverTime"] = now();
        data["imageCapabilities"] = capabilities();
        return ApiResponse::ok(data);
    }
    if (path == "/api/export") {
        auto kind = req->getParameter("kind");
        if (kind.empty())
            kind = "events";
        require(kinds.count(kind) || kind == "audit", "不支持的导出类型");
        auto rows = kind == "audit" ? audits(db, 100000) : db.items(kind);
        std::string output = "\xEF\xBB\xBF";
        if (!rows.empty()) {
            auto headers = rows[0].getMemberNames();
            for (size_t i = 0; i < headers.size(); i++) {
                if (i)
                    output += ',';
                output += csvCell(headers[i]);
            }
            output += "\r\n";
            for (const auto &row : rows) {
                for (size_t i = 0; i < headers.size(); i++) {
                    if (i)
                        output += ',';
                    auto v = row[headers[i]];
                    output += csvCell(v.isString() ? v.asString() : dump(v));
                }
                output += "\r\n";
            }
        }
        db.audit(actor, "导出数据", kind, "导出 " + std::to_string(rows.size()) + " 条记录", ip);
        return raw(output, "text/csv; charset=utf-8", "sentinel-" + kind + ".csv");
    }
    auto object = req->getJsonObject();
    require(object && object->isObject(), "请求体必须为 JSON 对象");
    auto payload = *object;
    require(req->body().size() <=
                (path == "/api/watermark-images/import" ? 15 * 1024 * 1024 : 128000),
            "请求体过大");
    if (path == "/api/watermark-images/import") {
        payload["action"] = "import";
        auto result = imageWorker(payload), info = result["info"];
        db.begin();
        db.query("SELECT pg_advisory_xact_lock(728114)");
        auto same = db.query("SELECT id FROM dlp_watermark_images WHERE hash=$1",
                             {info["hash"].asString()});
        if (same.size()) {
            Json::Value out;
            out["duplicate"] = true;
            out["id"] = same.get(0, "id");
            db.commit();
            return ApiResponse::ok(out);
        }
        auto total = db.query("SELECT count(*) AS count,coalesce(sum(octet_length(original)),0) AS "
                              "bytes FROM dlp_watermark_images");
        require(std::stoll(total.get(0, "count")) < 200 &&
                    std::stoll(total.get(0, "bytes")) + info["size"].asInt64() <= 300 * 1024 * 1024,
                "原型最多保存200张图片、总容量300 MB");
        auto meta = payload.get("metadata", Json::Value(Json::objectValue));
        require(meta.isObject(), "无效的图片关联信息");
        auto title = text(payload, "title", "", 100);
        if (title.empty()) {
            title = info["filename"].asString();
            auto dot = title.rfind('.');
            if (dot != std::string::npos)
                title.resize(dot);
            if (title.size() > 100)
                title = "导入的水印图片";
        }
        meta["title"] = title;
        meta["note"] = text(payload, "note", "", 1000);
        meta = metadata(meta);
        policyExists(db, meta);
        auto item = meta;
        merge(item, info);
        auto id = randomId("WIMG-");
        item["id"] = id;
        item["importedAt"] = now();
        item["updated"] = now();
        auto actorRow = db.query("SELECT username FROM users WHERE id=$1", {std::to_string(actor)});
        item["actor"] = actorRow.get(0, "username");
        item["ocrText"] = "";
        item["ocrState"] = "not_run";
        item["ocrTime"] = "";
        db.put("watermarkImages", item);
        db.query("INSERT INTO dlp_watermark_images(id,original,thumbnail,hash,mime) "
                 "VALUES($1,decode($2,'base64'),decode($3,'base64'),$4,$5)",
                 {id, result["original"].asString(), result["thumbnail"].asString(),
                  info["hash"].asString(), info["mime"].asString()});
        db.audit(actor, "导入水印图片", info["filename"].asString(),
                 "SHA-256 " + info["hash"].asString(), ip);
        db.commit();
        Json::Value out;
        out["duplicate"] = false;
        out["id"] = id;
        out["item"] = item;
        return ApiResponse::ok(out);
    }
    if (path.rfind("/api/watermark-images/", 0) == 0) {
        auto id = text(payload, "id");
        Json::Value extracted;
        if (path == "/api/watermark-images/ocr") {
            auto r = db.query("SELECT encode(original,'base64') AS original FROM "
                              "dlp_watermark_images WHERE id=$1",
                              {id});
            require(r.size(), "水印图片不存在");
            Json::Value work;
            work["action"] = "ocr";
            work["original"] = r.get(0, "original");
            auto encoded = work["original"].asString();
            encoded.erase(std::remove(encoded.begin(), encoded.end(), '\n'), encoded.end());
            work["original"] = encoded;
            work["endpoints"] = db.items("endpoints");
            work["policies"] = db.items("watermarks");
            extracted = imageWorker(work);
        }
        db.begin();
        auto item = db.get("watermarkImages", id, true);
        require(!item.isNull(), "水印图片不存在或已删除");
        if (path == "/api/watermark-images/delete") {
            db.query("DELETE FROM dlp_watermark_images WHERE id=$1", {id});
            db.query("DELETE FROM dlp_records WHERE kind='watermarkImages' AND id=$1", {id});
            db.audit(actor, "删除水印图片", item["filename"].asString(), id, ip);
            db.commit();
            return ApiResponse::ok();
        }
        if (path == "/api/watermark-images/ocr") {
            item["ocrText"] = extracted["text"];
            item["ocrState"] = extracted["text"].asString().empty() ? "empty" : "completed";
            item["ocrTime"] = now();
            db.put("watermarkImages", item);
            db.audit(actor, "识别水印图片文字", item["filename"].asString(), "识别结果待人工核验",
                     ip);
            db.commit();
            Json::Value out;
            out["item"] = item;
            out["suggestions"] = extracted["suggestions"];
            return ApiResponse::ok(out);
        }
        require(path == "/api/watermark-images/save", "接口不存在");
        auto meta = metadata(payload["metadata"]);
        policyExists(db, meta);
        merge(item, meta);
        item["updated"] = now();
        db.put("watermarkImages", item);
        db.audit(actor, "保存水印图片信息", item["title"].asString(), id, ip);
        db.commit();
        Json::Value out;
        out["item"] = item;
        return ApiResponse::ok(out);
    }
    if (path == "/api/save") {
        auto kind = text(payload, "kind");
        auto item = payload["item"];
        require(item.isObject(), "配置必须为对象");
        if (kind == "watermarks")
            item = watermark(item);
        else {
            require(kind == "policies" || kind == "rules", "不支持的配置类型");
            item["name"] = text(item, "name", "", 80);
            require(!item["name"].asString().empty(), "请填写有效名称");
            require(!item.isMember("enabled") || item["enabled"].isBool(), "enabled 必须为布尔值");
            item["enabled"] = item.get("enabled", true);
        }
        if (text(item, "id").empty())
            item["id"] = randomId(kind == "watermarks" ? "WM-"
                                  : kind == "policies" ? "POL-"
                                                       : "CLS-",
                                  4);
        item["updated"] = now();
        db.begin();
        db.put(kind, item);
        db.audit(actor, kind == "watermarks" ? "保存水印策略" : "保存配置", item["name"].asString(),
                 kind, ip);
        db.commit();
        Json::Value out;
        out["item"] = item;
        return ApiResponse::ok(out);
    }
    if (path == "/api/update") {
        const std::map<std::string, std::set<std::string>> allowed = {
            {"events", {"status", "note"}},
            {"endpoints", {"isolated", "policy"}},
            {"policies", {"enabled"}},
            {"rules", {"enabled"}},
            {"approvals", {"status", "comment"}},
            {"watermarks", {"enabled"}}};
        auto kind = text(payload, "kind");
        auto ids = payload["ids"], changes = payload["changes"];
        require(allowed.count(kind) && ids.isArray() && ids.size() <= 1000 && changes.isObject(),
                "无效更新");
        for (const auto &key : changes.getMemberNames()) {
            require(allowed.at(kind).count(key), "不支持的更新字段");
            if (key == "enabled" || key == "isolated")
                require(changes[key].isBool(), "开关必须为布尔值");
            else
                require(changes[key].isString() && changes[key].asString().size() <= 8000,
                        "更新字段无效");
        }
        if (kind == "events" && changes.isMember("status"))
            require(std::set<std::string>{"pending", "processing", "resolved"}.count(
                        changes["status"].asString()),
                    "无效事件状态");
        if (kind == "approvals")
            require(changes["status"].isString() &&
                        std::set<std::string>{"approved", "rejected"}.count(
                            changes["status"].asString()),
                    "无效审批结果");
        if (kind == "watermarks")
            require(changes["enabled"].isBool(), "水印启停状态必须为布尔值");
        db.begin();
        int count = 0;
        std::set<std::string> seen;
        for (const auto &value : ids) {
            require(value.isString(), "编号无效");
            auto id = value.asString();
            if (!seen.insert(id).second)
                continue;
            auto item = db.get(kind, id, true);
            if (item.isNull() || (kind == "approvals" && item["status"] != "pending"))
                continue;
            merge(item, changes);
            if (kind == "watermarks")
                item["updated"] = now();
            db.put(kind, item);
            db.audit(actor,
                     kind == "events"      ? "处置事件"
                     : kind == "approvals" ? "审批外发"
                     : kind == "endpoints" ? "终端管控"
                                           : "切换策略",
                     id, dump(changes), ip);
            count++;
        }
        db.commit();
        Json::Value out;
        out["count"] = count;
        return ApiResponse::ok(out);
    }
    if (path == "/api/delete") {
        auto kind = text(payload, "kind"), id = text(payload, "id");
        require(kind == "policies" || kind == "rules" || kind == "watermarks", "不支持删除");
        db.begin();
        db.query("DELETE FROM dlp_records WHERE kind=$1 AND id=$2", {kind, id});
        db.audit(actor, "删除配置", id, kind, ip);
        db.commit();
        return ApiResponse::ok();
    }
    if (path == "/api/scan") {
        auto scope = text(payload, "scope", "全体终端");
        require(scopes.count(scope), "无效扫描范围");
        db.begin();
        db.query("SELECT pg_advisory_xact_lock(728113)");
        for (const auto &s : db.items("scans"))
            require(s["status"] != "running" ||
                        std::time(nullptr) - s["createdAt"].asDouble() >= 20,
                    "已有扫描任务正在执行");
        Json::Value item;
        item["id"] = randomId("SCAN-", 3);
        item["name"] = text(payload, "name", "敏感数据发现任务", 80);
        require(!item["name"].asString().empty(), "任务名称不能为空");
        item["scope"] = scope;
        item["status"] = "running";
        item["progress"] = 0;
        item["found"] = 0;
        item["started"] = now();
        item["createdAt"] = Json::Int64(std::time(nullptr));
        db.put("scans", item);
        db.audit(actor, "创建扫描任务", item["name"].asString(), scope, ip);
        db.commit();
        Json::Value out;
        out["item"] = item;
        return ApiResponse::ok(out);
    }
    if (path == "/api/detect") {
        auto content = text(payload, "content", "", 30000);
        Json::Value hits(Json::arrayValue);
        for (const auto &rule : db.items("rules"))
            if (rule.get("enabled", false).asBool()) {
                Json::Value matches(Json::arrayValue);
                auto words = rule["keywords"].asString();
                size_t fullwidth = 0;
                while ((fullwidth = words.find("，", fullwidth)) != std::string::npos)
                    words.replace(fullwidth, 3, ",");
                std::istringstream stream(words);
                std::string word;
                while (std::getline(stream, word, ',')) {
                    Json::Value w;
                    w["value"] = word;
                    word = text(w, "value");
                    if (word.empty())
                        continue;
                    int count = 0;
                    size_t pos = 0;
                    while ((pos = content.find(word, pos)) != std::string::npos) {
                        count++;
                        pos += word.size();
                    }
                    if (count) {
                        Json::Value m;
                        m["value"] = word;
                        m["count"] = count;
                        matches.append(m);
                    }
                }
                if (rule["name"] == "个人信息")
                    for (const auto &spec : std::vector<std::pair<std::string, std::string>>{
                             {"手机号码", "1[3-9][0-9]{9}"}, {"身份证号", "[0-9]{17}[0-9Xx]"}}) {
                        std::regex pattern(spec.second);
                        int count = 0;
                        for (auto it =
                                 std::sregex_iterator(content.begin(), content.end(), pattern);
                             it != std::sregex_iterator(); ++it) {
                            auto start = it->position(), end = start + it->length();
                            if ((start == 0 ||
                                 !std::isdigit(static_cast<unsigned char>(content[start - 1]))) &&
                                (end == static_cast<long>(content.size()) ||
                                 !std::isdigit(static_cast<unsigned char>(content[end]))))
                                count++;
                        }
                        if (count) {
                            Json::Value m;
                            m["value"] = spec.first;
                            m["count"] = count;
                            matches.append(m);
                        }
                    }
                if (!matches.empty()) {
                    Json::Value hit;
                    hit["rule"] = rule["name"];
                    hit["level"] = rule["level"];
                    hit["matches"] = matches;
                    int count = 0;
                    for (const auto &m : matches)
                        count += m["count"].asInt();
                    hit["count"] = count;
                    hits.append(hit);
                }
            }
        db.audit(actor, "规则检测测试", "内容识别引擎",
                 "命中 " + std::to_string(hits.size()) + " 类规则", ip);
        Json::Value out;
        out["hits"] = hits;
        out["mode"] = "demo";
        return ApiResponse::ok(out);
    }
    if (path == "/api/settings") {
        db.begin();
        auto current = db.query("SELECT data::text FROM dlp_settings WHERE id=1 FOR UPDATE");
        require(current.size(), "系统设置尚未初始化");
        auto settings = parse(current.get(0, "data"));
        for (const auto &key : settings.getMemberNames())
            if (payload.isMember(key))
                settings[key] = payload[key];
        settings["company"] = text(settings, "company", "", 100);
        require(!settings["company"].asString().empty() && settings["retention"].isInt() &&
                    settings["retention"].asInt() >= 7 && settings["retention"].asInt() <= 3650,
                "请填写企业名称，日志保留天数需在7–3650天之间");
        for (auto key : {"offlineProtection", "autoUpdate", "notification"})
            if (settings.isMember(key))
                require(settings[key].isBool(), "设置开关必须为布尔值");
        db.query("UPDATE dlp_settings SET data=$1::jsonb WHERE id=1", {dump(settings)});
        db.audit(actor, "更新系统设置", "系统配置", "", ip);
        db.commit();
        return ApiResponse::ok();
    }
    if (path == "/api/report") {
        auto period = text(payload, "period", "最近7天");
        require(period == "最近7天" || period == "最近30天" || period == "全部数据",
                "统计周期无效");
        int days = period == "最近7天" ? 7 : period == "最近30天" ? 30 : 36500;
        auto cutoffTime = std::time(nullptr) - static_cast<time_t>(days) * 86400;
        std::tm tm{};
        localtime_r(&cutoffTime, &tm);
        std::ostringstream cutoff;
        cutoff << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
        int total = 0, blocked = 0, high = 0, pending = 0;
        for (const auto &e : db.items("events"))
            if (e["time"].asString() >= cutoff.str()) {
                total++;
                blocked += e["action"] == "blocked";
                high += e["severity"] == "high";
                pending += e["status"] == "pending";
            }
        Json::Value item;
        item["id"] = randomId("RPT-", 3);
        item["name"] = text(payload, "name", "数据安全运营报告", 80);
        require(!item["name"].asString().empty(), "请填写报告名称");
        item["period"] = period;
        item["time"] = now();
        item["status"] = "completed";
        item["events"] = total;
        item["blocked"] = blocked;
        item["high"] = high;
        item["pending"] = pending;
        item["endpoints"] = db.items("endpoints").size();
        item["assets"] = db.items("assets").size();
        db.begin();
        db.put("reports", item);
        db.audit(actor, "生成报告", item["name"].asString(), "", ip);
        db.commit();
        Json::Value out;
        out["item"] = item;
        return ApiResponse::ok(out);
    }
    throw std::invalid_argument("接口不存在");
}
void enqueue(const HttpRequestPtr &req, std::function<void(const HttpResponsePtr &)> callback,
             std::string id = "") {
    if (!WorkerPool::instance().push([req, callback, id] {
            try {
                callback(dispatch(req, id));
            } catch (const std::invalid_argument &e) {
                callback(ApiResponse::error(e.what()));
            } catch (const Json::Exception &e) {
                callback(ApiResponse::error("请求参数类型不正确"));
            } catch (const std::exception &e) {
                LOG_ERROR << "DLP request failed: " << req->path() << " " << e.what();
                callback(ApiResponse::error("服务器处理失败，请检查数据库与服务日志"));
            }
        }))
        callback(ApiResponse::error("服务繁忙，请稍后重试"));
}
} // namespace
void DlpController::handle(const HttpRequestPtr &req,
                           std::function<void(const HttpResponsePtr &)> &&callback) {
    enqueue(req, std::move(callback));
}
void DlpController::image(const HttpRequestPtr &req,
                          std::function<void(const HttpResponsePtr &)> &&callback, std::string id) {
    enqueue(req, std::move(callback), std::move(id));
}
