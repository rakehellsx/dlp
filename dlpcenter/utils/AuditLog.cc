#include "AuditLog.h"
#include <drogon/drogon.h>

using namespace drogon;

static void onAuditDone(const orm::Result &) {}

static void onAuditErr(const orm::DrogonDbException &e) {
    LOG_ERROR << "audit log insert error: " << e.base().what();
}

void auditLog(int operatorId, const std::string &action, const std::string &target,
              const std::string &detail, const std::string &ip, bool success) {
    auto db = app().getDbClient();
    if (!db)
        return;
    db->execSqlAsync("INSERT INTO operation_logs "
                     "(operator_id, operator_name, action, target, detail, ip, success) "
                     "VALUES ($1, (SELECT username FROM users WHERE id = $1), $2, $3, $4, $5, $6)",
                     &onAuditDone, &onAuditErr, operatorId, action, target, detail, ip, success);
}
