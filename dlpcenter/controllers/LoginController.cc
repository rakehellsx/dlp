#include "LoginController.h"
#include "utils/ApiResponse.h"
#include "utils/AuditLog.h"
#include <drogon/drogon.h>
#include "utils/Password.h"
#include "utils/Platform.h"
#include "utils/AuthToken.h"
#include <random>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <cctype>

using namespace drogon;
using std::placeholders::_1;
using std::placeholders::_2;

// ================= 工具函数 =================

// 生成 64 位十六进制随机 Token
static std::string generateToken() {
    unsigned char bytes[32];
    if (RAND_bytes(bytes, sizeof bytes) != 1)
        throw std::runtime_error("Token generation failed");
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (auto c : bytes)
        out << std::setw(2) << static_cast<int>(c);
    return out.str();
}

// time_point 格式化为 PG timestamp 字符串
static std::string formatTimestamp(std::chrono::system_clock::time_point tp) {
    std::time_t t = std::chrono::system_clock::to_time_t(tp);
    auto tm = dlp::utcTime(t);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S") << "+00:00";
    return oss.str();
}

// 校验字符串是否为 64 位十六进制（即客户端发来的 sha256 哈希）
static bool isValidSha256Hex(const std::string &s) {
    if (s.size() != 64)
        return false;
    for (unsigned char c : s) {
        if (!std::isxdigit(c))
            return false;
    }
    return true;
}

// ================= Token 校验（供 AuthFilter / AdminFilter 调用） =================
// 同时校验：token 存在、未过期、所属用户未禁用
// 查询成功回调
static void onValidateOk(std::function<void(bool, int)> cb, const orm::Result &r) {
    if (r.empty())
        cb(false, 0);
    else
        cb(true, r[0]["user_id"].as<int>());
}

// 查询失败回调：数据库异常按未登录处理
static void onValidateErr(std::function<void(bool, int)> cb, const orm::DrogonDbException &e) {
    LOG_ERROR << "validateTokenDb error: " << e.base().what();
    cb(false, 0);
}

void validateTokenDb(const std::string &token, std::function<void(bool, int)> callback) {
    auto db = app().getDbClient();
    if (!db) {
        callback(false, 0);
        return;
    }
    db->execSqlAsync(
        "SELECT t.user_id FROM user_tokens t "
        "JOIN users u ON u.id = t.user_id "
        "WHERE t.token = $1 AND t.expire_at > now() AND u.disabled = false",
        std::function<void(const drogon::orm::Result &)>(std::bind(&onValidateOk, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&onValidateErr, callback, _1)),
        token);
}

// ================= 登录 / 登出 =================
//
// 密码安全约定：
//   1. 客户端在本地对原始密码做 SHA-256，提交 64 位十六进制哈希（字段 password_hash），
//      网络上绝不传输明文密码；
//   2. 服务端对该哈希再做 bcrypt(cost=10) 校验/存储，防止拖库后彩虹表攻击。
//   3. 生产环境务必配合 HTTPS，防止哈希在传输中被截获重放。

void LoginController::login(const HttpRequestPtr &req, RespCallback &&callback) {
    auto json = req->getJsonObject();
    if (!json || !json->isObject() || !(*json)["username"].isString() ||
        !(*json)["password_hash"].isString()) {
        callback(ApiResponse::error("username/password_hash required"));
        return;
    }
    std::string username = (*json)["username"].asString();
    std::string clientHash = (*json)["password_hash"].asString();
    std::string ip = clientIp(req);

    // 基本格式校验：必须是 64 位十六进制
    if (username.empty() || username.size() > 64 || username.find('\0') != std::string::npos ||
        !isValidSha256Hex(clientHash)) {
        callback(ApiResponse::error("password_hash 必须是 64 位十六进制 SHA-256 值"));
        return;
    }

    // 禁用用户直接不允许登录
    app().getDbClient()->execSqlAsync(
        "SELECT id, password_hash FROM users WHERE username = $1 AND disabled = false",
        std::function<void(const drogon::orm::Result &)>(std::bind(
            &LoginController::onLoginQueryOk, this, clientHash, username, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&LoginController::onLoginQueryErr, this, username, ip, callback, _1)),
        username);
}

// 用户名查询成功：用客户端哈希做 bcrypt 校验，通过则生成并入库 Token
void LoginController::onLoginQueryOk(std::string clientHash, std::string username, std::string ip,
                                     RespCallback callback, const orm::Result &r) {
    if (r.empty() || !BCrypt::validatePassword(clientHash, r[0]["password_hash"].c_str())) {
        // 统一报错，不区分"用户不存在"和"密码错误"，避免用户名枚举
        auditLog(0, "login", username, "用户名或密码错误", ip, false);
        callback(ApiResponse::error("用户名或密码错误"));
        return;
    }

    int userId = r[0]["id"].as<int>();
    std::string token = generateToken();
    auto expireAt =
        formatTimestamp(std::chrono::system_clock::now() + std::chrono::seconds(TOKEN_TTL_SECONDS));

    app().getDbClient()->execSqlAsync(
        "INSERT INTO user_tokens (user_id, token, expire_at) VALUES ($1, $2, CURRENT_TIMESTAMP + "
        "interval '24 hours')",
        std::function<void(const drogon::orm::Result &)>(std::bind(
            &LoginController::onTokenInserted, this, userId, username, ip, callback, token, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&LoginController::onTokenInsertErr, this, username, ip, callback, _1)),
        userId, token);
}

void LoginController::onLoginQueryErr(std::string username, std::string ip, RespCallback callback,
                                      const orm::DrogonDbException &e) {
    LOG_ERROR << "login query error: " << e.base().what();
    auditLog(0, "login", username, "数据库异常", ip, false);
    callback(ApiResponse::error("internal error"));
}

// Token 入库成功：审计 + 返回给客户端
void LoginController::onTokenInserted(int userId, std::string username, std::string ip,
                                      RespCallback callback, std::string token,
                                      const orm::Result &) {
    auditLog(userId, "login", username, "", ip, true);

    Json::Value ret;
    ret["token"] = token;
    ret["expire_in"] = TOKEN_TTL_SECONDS;
    auto response = ApiResponse::ok(ret);
    response->addHeader("Set-Cookie", "dlp_token=" + token +
                                          "; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400");
    callback(response);
}

void LoginController::onTokenInsertErr(std::string username, std::string ip, RespCallback callback,
                                       const orm::DrogonDbException &e) {
    LOG_ERROR << "insert token error: " << e.base().what();
    auditLog(0, "login", username, "Token 写入失败", ip, false);
    callback(ApiResponse::error("internal error"));
}

// POST /api/logout（AuthFilter 已校验登录态）
void LoginController::logout(const HttpRequestPtr &req, RespCallback &&callback) {
    std::string token = requestToken(req); // 去掉 "Bearer "
    int operatorId = req->attributes()->get<int>("userId");
    std::string ip = clientIp(req);

    app().getDbClient()->execSqlAsync(
        "DELETE FROM user_tokens WHERE token = $1",
        std::function<void(const drogon::orm::Result &)>(
            std::bind(&LoginController::onLogoutOk, this, operatorId, ip, callback, _1)),
        std::function<void(const drogon::orm::DrogonDbException &)>(
            std::bind(&LoginController::onLogoutErr, this, operatorId, ip, callback, _1)),
        token);
}

void LoginController::onLogoutOk(int operatorId, std::string ip, RespCallback callback,
                                 const orm::Result &) {
    auditLog(operatorId, "logout", "", "", ip, true);
    Json::Value ret;
    ret["msg"] = "已退出登录";
    auto response = ApiResponse::ok(ret);
    response->addHeader("Set-Cookie", "dlp_token=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0");
    callback(response);
}

void LoginController::onLogoutErr(int operatorId, std::string ip, RespCallback callback,
                                  const orm::DrogonDbException &e) {
    LOG_ERROR << "logout error: " << e.base().what();
    auditLog(operatorId, "logout", "", "数据库异常", ip, false);
    callback(ApiResponse::error("internal error"));
}
