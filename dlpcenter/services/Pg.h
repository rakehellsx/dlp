#pragma once
#include <libpq-fe.h>
#include <json/json.h>
#include <vector>
#include <string>
#include <stdexcept>
#include "utils/Platform.h"
namespace dlp {
std::string dump(const Json::Value &v);
Json::Value parse(const std::string &s);
std::string now();
std::string randomId(const std::string &prefix, int bytes = 6);
class Result {
    PGresult *value_;

  public:
    explicit Result(PGresult *v) : value_(v) {}
    ~Result() {
        PQclear(value_);
    }
    Result(const Result &) = delete;
    Result(Result &&r) : value_(r.value_) {
        r.value_ = nullptr;
    }
    int size() const {
        return PQntuples(value_);
    }
    std::string get(int row, const char *column) const {
        return PQgetvalue(value_, row, PQfnumber(value_, column));
    }
    long affected() const {
        auto v = PQcmdTuples(value_);
        return v && *v ? std::stol(v) : 0;
    }
};
class Pg {
    PGconn *connection_;

  public:
    Pg();
    ~Pg();
    Pg(const Pg &) = delete;
    Result query(const std::string &sql, const std::vector<std::string> &args = {});
    void begin();
    void commit();
    Json::Value items(const std::string &kind);
    Json::Value get(const std::string &kind, const std::string &id, bool lock = false);
    void put(const std::string &kind, const Json::Value &item);
    void audit(int actor, const std::string &action, const std::string &target,
               const std::string &detail, const std::string &ip);
};
} // namespace dlp
