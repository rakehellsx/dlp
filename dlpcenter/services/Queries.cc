#include "Queries.h"
#include <map>
#include <set>
#include <regex>
#include <algorithm>
namespace dlp {
namespace {
const std::map<std::string, std::vector<std::string>> fields = {
    {"events", {"id", "title", "file", "user", "endpoint", "ip", "department"}},
    {"endpoints", {"id", "endpointUid", "name", "user", "ip", "department"}},
    {"policies", {"id", "name", "rule", "scope", "description"}},
    {"rules", {"id", "name", "description", "keywords"}},
    {"assets", {"id", "name", "endpoint", "owner", "path"}},
    {"approvals", {"id", "user", "file", "recipient", "reason"}},
    {"reports", {"id", "name", "period"}},
    {"scans", {"id", "name", "scope"}},
    {"watermarks", {"id", "name", "content", "scope", "description"}},
    {"watermarkImages",
     {"id", "title", "filename", "content", "code", "user", "endpoint", "ip", "note"}},
    {"audit", {"actor", "action", "target", "detail", "ip"}}};
void check(bool yes, const std::string &why) {
    if (!yes)
        throw std::invalid_argument(why);
}
Json::Value one(Pg &db, const std::string &sql, const std::vector<std::string> &p = {}) {
    auto r = db.query(sql, p);
    return r.size() ? parse(r.get(0, "value")) : Json::Value();
}
std::string param(std::vector<std::string> &p, const std::string &v) {
    p.push_back(v);
    return "$" + std::to_string(p.size());
}
int number(const Json::Value &q, const char *key, int fallback, int maximum) {
    if (!q.isMember(key) || q[key].asString().empty())
        return fallback;
    auto s = q[key].asString();
    check(std::regex_match(s, std::regex("[0-9]{1,7}")), "无效分页参数");
    int n = std::stoi(s);
    check(n >= 1 && n <= maximum, "分页参数超出范围");
    return n;
}
std::string source(const std::string &kind) {
    if (kind == "audit")
        return "(SELECT id, jsonb_build_object('id',id,'time',to_char(created_at AT TIME ZONE "
               "'Asia/Shanghai','YYYY-MM-DD "
               "HH24:MI:SS'),'actor',coalesce(operator_name,'未登录'),'action',action,'target',"
               "coalesce(target,''),'detail',coalesce(detail,''),'ip',coalesce(ip,''),'success',"
               "success) AS data FROM operation_logs) r";
    return "dlp_record_view r";
}
Json::Value rows(Pg &db, const std::string &sql, const std::vector<std::string> &p = {}) {
    return one(
        db, "SELECT coalesce(jsonb_agg(data),'[]'::jsonb) AS value FROM (" + sql + ") selected", p);
}
} // namespace
Json::Value listRecords(Pg &db, const std::string &kind, const Json::Value &q, bool exportAll) {
    check(fields.count(kind), "不支持的查询类型");
    std::vector<std::string> p;
    std::string where = kind == "audit" ? "true" : "r.kind=" + param(p, kind);
    auto word = q.get("q", "").asString();
    check(word.size() <= 800 && word.find('\0') == std::string::npos, "检索词过长或无效");
    if (!word.empty()) {
        std::string expression = "concat_ws(' '";
        for (auto &f : fields.at(kind))
            expression += ",r.data->>'" + f + "'";
        expression += ")";
        where += " AND strpos(lower(" + expression + "),lower(" + param(p, word) + "))>0";
    }
    const std::set<std::string> allowed = {
        "status", "severity",   "channel",  "department", "action",   "risk", "scope",
        "type",   "endpointId", "endpoint", "owner",      "policyId", "rule", "os"};
    for (auto &f : allowed)
        if (q.isMember(f) && !q[f].asString().empty())
            where += " AND r.data->>'" + f + "'=" + param(p, q[f].asString());
    if (q.isMember("endpointUid") && !q["endpointUid"].asString().empty()) {
        auto uid = q["endpointUid"].asString();
        check(
            std::regex_match(uid, std::regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")),
            "无效终端唯一标识");
        where += " AND r.endpoint_uid=" + param(p, uid) + "::uuid";
    }
    if (q.isMember("enabledState") && !q["enabledState"].asString().empty()) {
        auto state = q["enabledState"].asString();
        check(state == "enabled" || state == "disabled", "无效启停状态");
        where += " AND coalesce(r.data->>'enabled','false')=" +
                 param(p, state == "enabled" ? "true" : "false");
    }
    for (auto name : {"from", "to"})
        if (q.isMember(name) && !q[name].asString().empty()) {
            auto date = q[name].asString();
            check(std::regex_match(date, std::regex("[0-9]{4}-[0-9]{2}-[0-9]{2}")), "无效查询日期");
            where += " AND (r.data->>'time')::timestamp " +
                     std::string(name == std::string("from") ? ">=" : "<") + " (" + param(p, date) +
                     "::date" + (name == std::string("to") ? "+interval '1 day'" : "") + ")";
        }
    auto total = db.query("SELECT count(*) AS total FROM " + source(kind) + " WHERE " + where, p);
    auto count = std::stoll(total.get(0, "total"));
    int size = number(q, "pageSize", 10, 100), page = number(q, "page", 1, 1000000);
    page = std::min<long long>(page, std::max<long long>(1, (count + size - 1) / size));
    const std::map<std::string, std::string> sort = {
        {"time", "r.data->>'time'"},
        {"name", "r.data->>'name'"},
        {"priority", "coalesce((r.data->>'priority')::int,0)"},
        {"importedAt", "r.data->>'importedAt'"},
        {"id", "r.id"}};
    std::string order = kind == "audit"             ? "r.id DESC"
                        : kind == "watermarks"      ? "coalesce((r.data->>'priority')::int,0),r.seq"
                        : kind == "watermarkImages" ? "r.data->>'importedAt' DESC,r.seq DESC"
                        : kind == "reports" || kind == "scans" ? "r.seq DESC"
                                                               : "r.seq";
    if (q.isMember("sort") && !q["sort"].asString().empty()) {
        auto key = q["sort"].asString(), direction = q.get("direction", "asc").asString();
        check(sort.count(key) && (direction == "asc" || direction == "desc"), "无效排序参数");
        order = sort.at(key) + (direction == "asc" ? " ASC" : " DESC") +
                (kind == "audit" ? ",r.id DESC" : ",r.seq");
    }
    std::string sql =
        "SELECT r.data FROM " + source(kind) + " WHERE " + where + " ORDER BY " + order;
    if (!exportAll)
        sql += " LIMIT " + param(p, std::to_string(size)) + "::int OFFSET " +
               param(p, std::to_string((page - 1) * size)) + "::int";
    Json::Value result;
    result["items"] = rows(db, sql, p);
    result["total"] = Json::Int64(count);
    result["page"] = page;
    result["pageSize"] = size;
    return result;
}
Json::Value reportSnapshot(Pg &db, int days) {
    return one(db, R"SQL(SELECT jsonb_build_object(
 'events',count(*),'blocked',count(*) FILTER(WHERE data->>'action'='blocked'),
 'high',count(*) FILTER(WHERE data->>'severity'='high'),'pending',count(*) FILTER(WHERE data->>'status'='pending'),
 'endpoints',(SELECT count(*) FROM dlp_record_view WHERE kind='endpoints'),
 'assets',(SELECT count(*) FROM dlp_record_view WHERE kind='assets')) AS value
 FROM dlp_record_view WHERE kind='events' AND (data->>'time')::timestamp <= localtimestamp
 AND ($1::int=0 OR (data->>'time')::timestamp >= CASE WHEN $1::int=1 THEN date_trunc('day',localtimestamp) ELSE localtimestamp-make_interval(days=>$1::int) END))SQL",
               {std::to_string(days)});
}
Json::Value lookups(Pg &db) {
    return one(db, R"SQL(SELECT jsonb_build_object(
 'preview',(SELECT data FROM dlp_record_view WHERE kind='endpoints' ORDER BY seq LIMIT 1),
 'departments',(SELECT coalesce(jsonb_agg(label ORDER BY position),'[]') FROM dlp_catalogs WHERE category='department'),
 'channels',(SELECT coalesce(jsonb_agg(jsonb_build_object('name',label,'icon',config->>'icon') ORDER BY position),'[]') FROM dlp_catalogs WHERE category='channel'),
 'rules',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'name',data->>'name') ORDER BY seq),'[]') FROM dlp_record_view WHERE kind='rules'),
 'watermarks',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'name',data->>'name','type',data->>'type') ORDER BY seq),'[]') FROM dlp_record_view WHERE kind='watermarks')) AS value)SQL");
}
Json::Value statistics(Pg &db, int days, int chartDays) {
    check((days == 1 || days == 7 || days == 30) && (chartDays == 7 || chartDays == 30),
          "无效统计周期");
    auto out = one(db, R"SQL(SELECT jsonb_build_object(
 'counts',(SELECT coalesce(jsonb_object_agg(kind,n),'{}') FROM (SELECT kind,count(*) n FROM dlp_record_view GROUP BY kind) t),
 'navigation',jsonb_build_object('pendingEvents',(SELECT count(*) FROM dlp_record_view WHERE kind='events' AND data->>'status'='pending'),'pendingApprovals',(SELECT count(*) FROM dlp_record_view WHERE kind='approvals' AND data->>'status'='pending'),'offlineEndpoints',(SELECT count(*) FROM dlp_record_view WHERE kind='endpoints' AND data->>'status'='offline')),
 'endpoints',(SELECT jsonb_build_object('total',count(*),'online',count(*) FILTER(WHERE data->>'status'='online'),'high',count(*) FILTER(WHERE data->>'risk'='high'),'isolated',count(*) FILTER(WHERE data->>'isolated'='true'),'coverage',coalesce(round(100.0*count(*) FILTER(WHERE data->>'status'='online')/nullif(count(*),0),1),0)) FROM dlp_record_view WHERE kind='endpoints'),
 'assets',(SELECT jsonb_build_object('total',count(*),'departments',count(DISTINCT data->>'department')) FROM dlp_record_view WHERE kind='assets'),
 'policies',(SELECT jsonb_build_object('total',count(*),'enabled',count(*) FILTER(WHERE data->>'enabled'='true'),'disabled',count(*) FILTER(WHERE data->>'enabled'<>'true')) FROM dlp_record_view WHERE kind='policies'),
 'enabledRules',(SELECT count(*) FROM dlp_record_view WHERE kind='rules' AND data->>'enabled'='true'),
 'eventTabs',(SELECT coalesce(jsonb_object_agg(status,n),'{}') FROM (SELECT data->>'status' status,count(*) n FROM dlp_record_view WHERE kind='events' GROUP BY data->>'status') t),
 'approvalTabs',(SELECT coalesce(jsonb_object_agg(status,n),'{}') FROM (SELECT data->>'status' status,count(*) n FROM dlp_record_view WHERE kind='approvals' GROUP BY data->>'status') t),
 'watermarks',(SELECT coalesce(jsonb_object_agg(type,jsonb_build_object('total',n,'enabled',enabled)),'{}') FROM (SELECT data->>'type' type,count(*) n,count(*) FILTER(WHERE data->>'enabled'='true') enabled FROM dlp_record_view WHERE kind='watermarks' GROUP BY data->>'type') t),
 'images',(SELECT jsonb_build_object('total',count(*),'pending',count(*) FILTER(WHERE data->>'status'='pending'),'reviewed',count(*) FILTER(WHERE data->>'status'='reviewed'),'bytes',coalesce(sum((data->>'size')::bigint),0)) FROM dlp_record_view WHERE kind='watermarkImages'),
 'ruleAssets',(SELECT coalesce(jsonb_object_agg(type,n),'{}') FROM (SELECT data->>'type' type,count(*) n FROM dlp_record_view WHERE kind='assets' GROUP BY data->>'type') t)) AS value)SQL");
    out["overview"] = reportSnapshot(db, days);
    out["trend"] = one(
        db,
        R"SQL(WITH buckets AS (SELECT i,localtimestamp-($1::int::numeric/7)*(7-i)*interval '1 day' starts,localtimestamp-($1::int::numeric/7)*(6-i)*interval '1 day' ends FROM generate_series(0,6) i)
 SELECT jsonb_agg(jsonb_build_object('label',to_char(ends,'MM/DD'),'all',total,'blocked',blocked) ORDER BY i) AS value FROM (
 SELECT b.*,count(r.id) total,count(r.id) FILTER(WHERE r.data->>'action'='blocked') blocked FROM buckets b LEFT JOIN dlp_record_view r ON r.kind='events' AND (r.data->>'time')::timestamp>b.starts AND (r.data->>'time')::timestamp<=b.ends GROUP BY b.i,b.starts,b.ends) t)SQL",
        {std::to_string(chartDays)});
    out["channels"] = one(
        db,
        R"SQL(SELECT coalesce(jsonb_agg(jsonb_build_object('name',c.label,'icon',c.config->>'icon','events',e.total,'blocked',e.blocked,'policies',p.total,'periodEvents',e.recent) ORDER BY c.position),'[]') AS value FROM dlp_catalogs c
 CROSS JOIN LATERAL (SELECT count(*) total,count(*) FILTER(WHERE data->>'action'='blocked') blocked,count(*) FILTER(WHERE (data->>'time')::timestamp<=localtimestamp AND (data->>'time')::timestamp>=CASE WHEN $1::int=1 THEN date_trunc('day',localtimestamp) ELSE localtimestamp-make_interval(days=>$1::int) END) recent FROM dlp_record_view WHERE kind='events' AND data->>'channel'=c.label) e
 CROSS JOIN LATERAL (SELECT count(*) total FROM dlp_record_view WHERE kind='policies' AND data->>'enabled'='true' AND (data->>'channels'='所有通道' OR strpos(data->>'channels',c.label)>0)) p WHERE c.category='channel')SQL",
        {std::to_string(days)});
    out["ranking"] = one(
        db,
        R"SQL(SELECT coalesce(jsonb_agg(jsonb_build_object('dep',dep,'n',n,'percent',percent) ORDER BY n DESC,dep),'[]') AS value FROM (
 SELECT data->>'department' dep,count(*) n,round(100.0*count(*)/max(count(*)) OVER(),1) percent FROM dlp_record_view WHERE kind='events' AND (data->>'time')::timestamp<=localtimestamp AND (data->>'time')::timestamp>=CASE WHEN $1::int=1 THEN date_trunc('day',localtimestamp) ELSE localtimestamp-make_interval(days=>$1::int) END GROUP BY data->>'department' ORDER BY n DESC,dep LIMIT 3) t)SQL",
        {std::to_string(days)});
    out["important"] = rows(
        db,
        R"SQL(SELECT data FROM dlp_record_view WHERE kind='events' AND data->>'status'<>'resolved' AND (data->>'time')::timestamp<=localtimestamp AND (data->>'time')::timestamp>=CASE WHEN $1::int=1 THEN date_trunc('day',localtimestamp) ELSE localtimestamp-make_interval(days=>$1::int) END ORDER BY data->>'time' DESC,seq DESC LIMIT 5)SQL",
        {std::to_string(days)});
    return out;
}
Json::Value recordDetail(Pg &db, const std::string &kind, const std::string &id) {
    check(fields.count(kind) && kind != "audit", "不支持的详情类型");
    auto item = db.get(kind, id);
    check(!item.isNull(), "记录不存在或已删除");
    Json::Value out;
    out["item"] = item;
    out["related"]["events"] = Json::Value(Json::arrayValue);
    out["related"]["eventCount"] = 0;
    const auto uid = item.get("endpointUid", "").asString();
    if (!uid.empty()) {
        out["related"]["endpoint"] = db.get("endpoints", uid);
        for (auto relatedKind : {"events", "assets", "approvals", "watermarkImages"}) {
            Json::Value q;
            q["endpointUid"] = uid;
            q["pageSize"] = "5";
            if (std::string(relatedKind) == "events") {
                q["sort"] = "time";
                q["direction"] = "desc";
            }
            auto result = listRecords(db, relatedKind, q);
            out["related"][relatedKind] = result["items"];
            out["related"][std::string(relatedKind) + "Count"] = result["total"];
            if (std::string(relatedKind) == "events")
                out["related"]["eventCount"] = result["total"];
        }
    }
    if (kind == "watermarkImages")
        out["related"]["policy"] = db.get("watermarks", item["policyId"].asString());
    return out;
}
void advanceScans(Pg &db) {
    db.query(
        R"SQL(UPDATE dlp_records s SET data=s.data||jsonb_build_object('progress',least(100,greatest(0,floor((extract(epoch FROM now())-(s.data->>'createdAt')::numeric)*5)))::int,
 'status',CASE WHEN extract(epoch FROM now())-(s.data->>'createdAt')::numeric>=20 THEN 'completed' ELSE 'running' END,
 'found',CASE WHEN extract(epoch FROM now())-(s.data->>'createdAt')::numeric>=20 THEN (SELECT count(*) FROM dlp_record_view a WHERE a.kind='assets' AND (s.data->>'scope'='全体终端' OR a.data->>'department'=s.data->>'scope')) ELSE coalesce((s.data->>'found')::int,0) END)
 WHERE s.kind='scans' AND s.data->>'status'='running')SQL");
}
} // namespace dlp
