#include "Pg.h"
#include <openssl/rand.h>
#include <sstream>
#include <iomanip>
#include <ctime>
#include <memory>
namespace dlp {
std::string dump(const Json::Value &v) {
    Json::StreamWriterBuilder w;
    w["indentation"] = "";
    return Json::writeString(w, v);
}
Json::Value parse(const std::string &s) {
    Json::Value v;
    Json::CharReaderBuilder b;
    std::string err;
    auto r = std::unique_ptr<Json::CharReader>(b.newCharReader());
    if (!r->parse(s.data(), s.data() + s.size(), &v, &err))
        throw std::invalid_argument("无效 JSON");
    return v;
}
std::string now() {
    auto t = std::time(nullptr);
    auto tm = chinaTime(t);
    std::ostringstream s;
    s << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
    return s.str();
}
std::string randomId(const std::string &p, int bytes) {
    unsigned char data[32];
    if (bytes > 32 || RAND_bytes(data, bytes) != 1)
        throw std::runtime_error("Random generator failed");
    std::ostringstream s;
    s << p << std::uppercase << std::hex << std::setfill('0');
    for (int i = 0; i < bytes; i++)
        s << std::setw(2) << int(data[i]);
    return s.str();
}
Pg::Pg() {
    auto host = env("DLP_DB_HOST", "127.0.0.1"), port = env("DLP_DB_PORT", "5432"),
         name = env("DLP_DB_NAME", "dlpcenter"), user = env("DLP_DB_USER", "dlpcenter"),
         password = env("DLP_DB_PASSWORD");
    const char *keys[] = {"host", "port", "dbname", "user", "password", "connect_timeout", nullptr};
    const char *values[] = {host.c_str(),     port.c_str(), name.c_str(), user.c_str(),
                            password.c_str(), "10",         nullptr};
    connection_ = PQconnectdbParams(keys, values, 0);
    if (PQstatus(connection_) != CONNECTION_OK) {
        PQfinish(connection_);
        throw std::runtime_error("PostgreSQL connection failed");
    }
    try {
        query("SET TIME ZONE 'Asia/Shanghai'");
        query("SET statement_timeout='30s'");
        query("SET lock_timeout='10s'");
    } catch (...) {
        PQfinish(connection_);
        throw;
    }
}
Pg::~Pg() {
    PQfinish(connection_);
}
Result Pg::query(const std::string &sql, const std::vector<std::string> &args) {
    std::vector<const char *> params;
    for (const auto &v : args)
        params.push_back(v.c_str());
    auto r = PQexecParams(connection_, sql.c_str(), params.size(), nullptr, params.data(), nullptr,
                          nullptr, 0);
    if (!r || !(PQresultStatus(r) == PGRES_TUPLES_OK || PQresultStatus(r) == PGRES_COMMAND_OK)) {
        if (r)
            PQclear(r);
        throw std::runtime_error("PostgreSQL query failed");
    }
    return Result(r);
}
void Pg::begin() {
    query("BEGIN");
}
void Pg::commit() {
    query("COMMIT");
}
Json::Value Pg::items(const std::string &kind) {
    Json::Value a(Json::arrayValue);
    auto r = query("SELECT data::text FROM dlp_record_view WHERE kind=$1 ORDER BY seq", {kind});
    for (int i = 0; i < r.size(); i++)
        a.append(parse(r.get(i, "data")));
    return a;
}
Json::Value Pg::get(const std::string &kind, const std::string &id, bool lock) {
    auto r =
        kind == "endpoints"
            ? query(
                  "SELECT data::text FROM endpoint_records WHERE id=$1 OR data->>'endpointUid'=$1" +
                      std::string(lock ? " FOR UPDATE" : ""),
                  {id})
            : query("SELECT data::text FROM dlp_records WHERE kind=$1 AND id=$2" +
                        std::string(lock ? " FOR UPDATE" : ""),
                    {kind, id});
    if (!r.size())
        return Json::Value();
    return parse(r.get(0, "data"));
}
void Pg::put(const std::string &kind, const Json::Value &item) {
    if (kind == "endpoints") {
        auto result =
            query("UPDATE endpoints SET name=$2,username=$3,department=$4,ip_address=$5,"
                  "os=$6,status=$7,risk=$8,agent_version=$9,policy=$10,last_seen=$11,isolated=$12::"
                  "boolean "
                  "WHERE endpoint_code=$1 AND endpoint_uid::text=$13",
                  {item["id"].asString(), item["name"].asString(), item["user"].asString(),
                   item["department"].asString(), item["ip"].asString(), item["os"].asString(),
                   item["status"].asString(), item["risk"].asString(), item["version"].asString(),
                   item["policy"].asString(), item["lastSeen"].asString(),
                   item["isolated"].asBool() ? "true" : "false", item["endpointUid"].asString()});
        if (!result.affected())
            throw std::invalid_argument("终端不存在或唯一标识不一致");
        return;
    }
    query("INSERT INTO dlp_records(kind,id,data) VALUES($1,$2,$3::jsonb) ON CONFLICT(kind,id) DO "
          "UPDATE SET data=EXCLUDED.data,endpoint_uid=EXCLUDED.endpoint_uid",
          {kind, item["id"].asString(), dump(item)});
}
void Pg::audit(int actor, const std::string &action, const std::string &target,
               const std::string &detail, const std::string &ip) {
    query("INSERT INTO operation_logs(operator_id,operator_name,action,target,detail,ip,success) "
          "VALUES($1,(SELECT username FROM users WHERE id=$1),$2,$3,$4,$5,true)",
          {std::to_string(actor), action, target, detail, ip});
}
} // namespace dlp
