#include "UserController.h"
#include "utils/ApiResponse.h"
#include "utils/AuditLog.h"
#include <drogon/drogon.h>
#include "utils/Password.h"
#include <sstream>

using namespace drogon;
using std::placeholders::_1;

// 校验字符串是否为 64 位十六进制（客户端提交的 sha256 哈希）
static bool isValidSha256Hex(const std::string &s) {
    if (s.size() != 64)
        return false;
    for (unsigned char c : s) {
        if (!std::isxdigit(c))
            return false;
    }
    return true;
}

// 校验 role 字段合法性
static bool isValidRole(const std::string &role) {
    return role == "user" || role == "admin";
}

// ================= 当前用户信息 =================

void UserController::profile(const HttpRequestPtr &req, RespCallback &&callback) {
    int userId = req->attributes()->get<int>("userId"); // AuthFilter 注入

    app().getDbClient()->execSqlAsync(
        "SELECT id, username, role, disabled, created_at FROM users WHERE id = $1",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&UserController::onProfileOk, this, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onProfileErr, this, callback, _1)),
        userId);
}

void UserController::onProfileOk(RespCallback callback, const orm::Result &r) {
    if (r.empty()) {
        callback(ApiResponse::error("user not found"));
        return;
    }
    Json::Value ret;
    ret["id"] = r[0]["id"].as<int>();
    ret["username"] = r[0]["username"].as<std::string>();
    ret["role"] = r[0]["role"].as<std::string>();
    ret["disabled"] = r[0]["disabled"].as<bool>();
    ret["created_at"] = r[0]["created_at"].as<std::string>();
    callback(ApiResponse::ok(ret));
}

void UserController::onProfileErr(RespCallback callback, const orm::DrogonDbException &e) {
    LOG_ERROR << "profile error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

// ================= 当前账号有效 Token 列表 =================

void UserController::listTokens(const HttpRequestPtr &req, RespCallback &&callback) {
    int userId = req->attributes()->get<int>("userId");

    app().getDbClient()->execSqlAsync(
        "SELECT token, expire_at, created_at FROM user_tokens "
        "WHERE user_id = $1 AND expire_at > now() ORDER BY created_at DESC",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&UserController::onListTokensOk, this, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onListTokensErr, this, callback, _1)),
        userId);
}

void UserController::onListTokensOk(RespCallback callback, const orm::Result &r) {
    Json::Value arr(Json::arrayValue);
    for (const auto &row : r) {
        Json::Value item;
        item["token"] = row["token"].as<std::string>();
        item["expire_at"] = row["expire_at"].as<std::string>();
        item["created_at"] = row["created_at"].as<std::string>();
        arr.append(item);
    }
    Json::Value ret;
    ret["count"] = (int)r.size();
    ret["tokens"] = arr;
    callback(ApiResponse::ok(ret));
}

void UserController::onListTokensErr(RespCallback callback, const orm::DrogonDbException &e) {
    LOG_ERROR << "listTokens error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

// ================= 修改密码（本人操作） =================
// POST /api/user/change_password
// body: {"old_password_hash":"<64位hex>","new_password_hash":"<64位hex>"}
void UserController::changePassword(const HttpRequestPtr &req, RespCallback &&callback) {
    int userId = req->attributes()->get<int>("userId");
    std::string ip = clientIp(req);

    auto json = req->getJsonObject();
    if (!json || !json->isObject() || !(*json)["old_password_hash"].isString() ||
        !(*json)["new_password_hash"].isString()) {
        callback(ApiResponse::error("old_password_hash/new_password_hash required"));
        return;
    }
    std::string oldHash = (*json)["old_password_hash"].asString();
    std::string newHash = (*json)["new_password_hash"].asString();

    if (!isValidSha256Hex(oldHash) || !isValidSha256Hex(newHash)) {
        callback(ApiResponse::error("密码哈希必须是 64 位十六进制 SHA-256 值"));
        return;
    }
    if (oldHash == newHash) {
        callback(ApiResponse::error("新密码不能与旧密码相同"));
        return;
    }

    // 查出当前密码哈希，与旧密码哈希做 bcrypt 校验
    app().getDbClient()->execSqlAsync(
        "SELECT password_hash FROM users WHERE id = $1",
        std::function<void(const drogon::orm::Result &)>(std::bind(
            &UserController::onPwdQueryOk, this, oldHash, newHash, userId, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onPwdQueryErr, this, userId, ip, callback, _1)),
        userId);
}

void UserController::onPwdQueryOk(std::string oldHash, std::string newHash, int userId,
                                  std::string ip, RespCallback callback, const orm::Result &r) {
    if (r.empty()) {
        callback(ApiResponse::error("user not found"));
        return;
    }
    // 校验旧密码
    if (!BCrypt::validatePassword(oldHash, r[0]["password_hash"].c_str())) {
        auditLog(userId, "change_password", "", "旧密码校验失败", ip, false);
        callback(ApiResponse::error("旧密码错误"));
        return;
    }
    // 旧密码正确：对新哈希做 bcrypt 后更新
    std::string storedHash = BCrypt::generateHash(newHash, 10);
    app().getDbClient()->execSqlAsync(
        "UPDATE users SET password_hash = $2 WHERE id = $1",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&UserController::onPwdUpdated, this, userId, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onPwdUpdateErr, this, userId, ip, callback, _1)),
        userId, storedHash);
}

void UserController::onPwdQueryErr(int userId, std::string ip, RespCallback callback,
                                   const orm::DrogonDbException &e) {
    LOG_ERROR << "changePassword query error: " << e.base().what();
    auditLog(userId, "change_password", "", "数据库异常", ip, false);
    callback(ApiResponse::error("internal error"));
}

void UserController::onPwdUpdated(int userId, std::string ip, RespCallback callback,
                                  const orm::Result &) {
    auditLog(userId, "change_password", "", "", ip, true);
    Json::Value ret;
    ret["msg"] = "密码修改成功，请重新登录";
    callback(ApiResponse::ok(ret));
}

void UserController::onPwdUpdateErr(int userId, std::string ip, RespCallback callback,
                                    const orm::DrogonDbException &e) {
    LOG_ERROR << "changePassword update error: " << e.base().what();
    auditLog(userId, "change_password", "", "数据库异常", ip, false);
    callback(ApiResponse::error("internal error"));
}

// ================= 新增用户（管理员） =================
// POST /api/user/create
// body: {"username":"...","password_hash":"<64位hex>","role":"user|admin"（可选）}
void UserController::createUser(const HttpRequestPtr &req, RespCallback &&callback) {
    int operatorId = req->attributes()->get<int>("userId");
    std::string ip = clientIp(req);

    auto json = req->getJsonObject();
    if (!json || !json->isObject() || !(*json)["username"].isString() ||
        !(*json)["password_hash"].isString() ||
        (json->isMember("role") && !(*json)["role"].isString())) {
        callback(ApiResponse::error("username/password_hash required"));
        return;
    }
    std::string username = (*json)["username"].asString();
    std::string passwordHash = (*json)["password_hash"].asString();
    std::string role = json->isMember("role") ? (*json)["role"].asString() : "user";

    if (username.empty() || username.size() > 64 || username.find('\0') != std::string::npos) {
        callback(ApiResponse::error("username 长度不合法(1-64)"));
        return;
    }
    if (!isValidSha256Hex(passwordHash)) {
        callback(ApiResponse::error("password_hash 必须是 64 位十六进制 SHA-256 值"));
        return;
    }
    if (!isValidRole(role)) {
        callback(ApiResponse::error("role 必须是 user 或 admin"));
        return;
    }

    // 先查重
    app().getDbClient()->execSqlAsync(
        "SELECT id FROM users WHERE username = $1",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&UserController::onCheckUserOkForCreate, this, username, passwordHash, role,
                      operatorId, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onCheckUserErrForCreate, this, callback, _1)),
        username);
}

void UserController::onCheckUserOkForCreate(std::string username, std::string passwordHash,
                                            std::string role, int operatorId, std::string ip,
                                            RespCallback callback, const orm::Result &r) {
    if (!r.empty()) {
        callback(ApiResponse::error("用户名已存在"));
        return;
    }

    // 服务端对客户端哈希再做 bcrypt（cost=10）后入库
    std::string storedHash = BCrypt::generateHash(passwordHash, 10);

    app().getDbClient()->execSqlAsync(
        "INSERT INTO users (username, password_hash, role) VALUES ($1, $2, $3) RETURNING id",
        std::function<void(const drogon::orm::Result &)>(std::bind(
            &UserController::onUserCreated, this, operatorId, username, role, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onUserCreateErr, this, callback, _1)),
        username, storedHash, role);
}

void UserController::onCheckUserErrForCreate(RespCallback callback,
                                             const orm::DrogonDbException &e) {
    LOG_ERROR << "createUser check error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

void UserController::onUserCreated(int operatorId, std::string username, std::string role,
                                   std::string ip, RespCallback callback, const orm::Result &r) {
    std::ostringstream detail;
    detail << "{\"role\":\"" << role << "\"}";
    auditLog(operatorId, "create", username, detail.str(), ip, true);

    Json::Value ret;
    ret["id"] = r[0]["id"].as<int>();
    ret["msg"] = "用户创建成功";
    callback(ApiResponse::ok(ret));
}

void UserController::onUserCreateErr(RespCallback callback, const orm::DrogonDbException &e) {
    LOG_ERROR << "createUser insert error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

// ================= 删除用户（管理员） =================
// POST /api/user/delete  body: {"username":"..."}
// 级联删除其所有 Token（user_tokens 表已建 ON DELETE CASCADE）
void UserController::deleteUser(const HttpRequestPtr &req, RespCallback &&callback) {
    int operatorId = req->attributes()->get<int>("userId"); // 操作人
    std::string ip = clientIp(req);

    auto json = req->getJsonObject();
    if (!json || !json->isObject() || !(*json)["username"].isString()) {
        callback(ApiResponse::error("username required"));
        return;
    }
    std::string username = (*json)["username"].asString();

    app().getDbClient()->execSqlAsync(
        "SELECT id FROM users WHERE username = $1",
        std::function<void(const drogon::orm::Result &)>(std::bind(
            &UserController::onCheckUserOkForDelete, this, username, operatorId, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onCheckUserErrForDelete, this, callback, _1)),
        username);
}

void UserController::onCheckUserOkForDelete(std::string username, int operatorId, std::string ip,
                                            RespCallback callback, const orm::Result &r) {
    if (r.empty()) {
        callback(ApiResponse::error("用户不存在"));
        return;
    }
    int targetId = r[0]["id"].as<int>();
    if (targetId == operatorId) {
        callback(ApiResponse::error("不能删除当前登录账号"));
        return;
    }

    // ON DELETE CASCADE 会自动清掉 user_tokens 中的记录
    app().getDbClient()->execSqlAsync(
        "DELETE FROM users WHERE id = $1",
        std::function<void(const drogon::orm::Result &)>(std::bind(
            &UserController::onUserDeleted, this, operatorId, username, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onUserDeleteErr, this, callback, _1)),
        targetId);
}

void UserController::onCheckUserErrForDelete(RespCallback callback,
                                             const orm::DrogonDbException &e) {
    LOG_ERROR << "deleteUser check error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

void UserController::onUserDeleted(int operatorId, std::string username, std::string ip,
                                   RespCallback callback, const orm::Result &) {
    auditLog(operatorId, "delete", username, "", ip, true);

    Json::Value ret;
    ret["msg"] = "用户已删除";
    callback(ApiResponse::ok(ret));
}

void UserController::onUserDeleteErr(RespCallback callback, const orm::DrogonDbException &e) {
    LOG_ERROR << "deleteUser error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

// ================= 禁用 / 启用用户（管理员） =================
// POST /api/user/disable  body: {"username":"...","disabled":true|false}
// 禁用后：该用户无法登录，其所有 Token 立即失效（主动清除）
void UserController::disableUser(const HttpRequestPtr &req, RespCallback &&callback) {
    int operatorId = req->attributes()->get<int>("userId");
    std::string ip = clientIp(req);

    auto json = req->getJsonObject();
    if (!json || !json->isObject() || !(*json)["username"].isString() ||
        !(*json)["disabled"].isBool()) {
        callback(ApiResponse::error("username/disabled required"));
        return;
    }
    std::string username = (*json)["username"].asString();
    bool disabled = (*json)["disabled"].asBool();

    app().getDbClient()->execSqlAsync(
        "SELECT id FROM users WHERE username = $1",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&UserController::onCheckUserOkForDisable, this, username, disabled,
                      operatorId, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onCheckUserErrForDisable, this, callback, _1)),
        username);
}

void UserController::onCheckUserOkForDisable(std::string username, bool disabled, int operatorId,
                                             std::string ip, RespCallback callback,
                                             const orm::Result &r) {
    if (r.empty()) {
        callback(ApiResponse::error("用户不存在"));
        return;
    }
    int targetId = r[0]["id"].as<int>();
    if (targetId == operatorId) {
        callback(ApiResponse::error("不能禁用/启用当前登录账号"));
        return;
    }

    app().getDbClient()->execSqlAsync(
        "UPDATE users SET disabled = $2 WHERE id = $1",
        std::function<void(const drogon::orm::Result &)>(std::bind(&UserController::onUserDisabled,
                                                                   this, operatorId, username,
                                                                   disabled, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onUserDisableErr, this, callback, _1)),
        targetId, disabled);
}

void UserController::onCheckUserErrForDisable(RespCallback callback,
                                              const orm::DrogonDbException &e) {
    LOG_ERROR << "disableUser check error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

// 禁用/启用更新成功；若本次操作是禁用，则清除该用户全部 Token 使其立即掉线
void UserController::onUserDisabled(int operatorId, std::string username, bool disabled,
                                    std::string ip, RespCallback callback, const orm::Result &) {
    if (!disabled) {
        // 启用：无需清 Token，直接审计并返回
        auditLog(operatorId, "enable", username, "", ip, true);
        Json::Value ret;
        ret["msg"] = "用户已启用";
        callback(ApiResponse::ok(ret));
        return;
    }

    app().getDbClient()->execSqlAsync(
        "DELETE FROM user_tokens WHERE user_id = (SELECT id FROM users WHERE username = $1)",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&UserController::onTokensClearedAfterDisable, this, operatorId, username, ip,
                      callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&UserController::onTokensClearErrAfterDisable, this, callback, _1)),
        username);
}

void UserController::onUserDisableErr(RespCallback callback, const orm::DrogonDbException &e) {
    LOG_ERROR << "disableUser update error: " << e.base().what();
    callback(ApiResponse::error("internal error"));
}

void UserController::onTokensClearedAfterDisable(int operatorId, std::string username,
                                                 std::string ip, RespCallback callback,
                                                 const orm::Result &) {
    auditLog(operatorId, "disable", username, "", ip, true);

    Json::Value ret;
    ret["msg"] = "用户已禁用，其登录态已全部清除";
    callback(ApiResponse::ok(ret));
}

void UserController::onTokensClearErrAfterDisable(RespCallback callback,
                                                  const orm::DrogonDbException &e) {
    LOG_ERROR << "clear tokens after disable error: " << e.base().what();
    // 用户已禁用，Token 清理失败不影响主流程，仅提示
    Json::Value ret;
    ret["msg"] = "用户已禁用（但登录态清理失败，Token 将在过期后失效）";
    callback(ApiResponse::ok(ret));
}
