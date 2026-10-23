#include "AdminFilter.h"
#include "controllers/LoginController.h" // validateTokenDb 声明
#include "utils/ApiResponse.h"
#include "utils/AuthToken.h"
#include <drogon/drogon.h>

using namespace drogon;
using std::placeholders::_1;
using std::placeholders::_2;

void AdminFilter::doFilter(const HttpRequestPtr &req, FilterCallback &&fcb,
                           FilterChainCallback &&fccb) {
    auto token = requestToken(req);
    if (!validTokenFormat(token)) {
        fcb(ApiResponse::error("未登录或Token已过期"));
        return;
    }
    if (!validCookieRequest(req)) {
        fcb(ApiResponse::error("无效请求来源"));
        return;
    }

    // 第一步：异步查库校验 Token（与 AuthFilter 相同）
    validateTokenDb(token, std::bind(&AdminFilter::onTokenChecked, req, std::move(fcb),
                                     std::move(fccb), _1, _2));
}

void AdminFilter::onTokenChecked(const HttpRequestPtr &req, FilterCallback fcb,
                                 FilterChainCallback fccb, bool ok, int userId) {
    if (!ok) {
        fcb(ApiResponse::error("未登录或Token已过期"));
        return;
    }

    // 注入 userId，供后续 Controller 使用（与 AuthFilter 行为一致）
    req->attributes()->insert("userId", userId);

    // 第二步：查用户角色
    app().getDbClient()->execSqlAsync("SELECT role FROM users WHERE id = $1",
                                      std::function<void(const drogon::orm::Result &)>(std::bind(
                                          &AdminFilter::onRoleChecked, req, fcb, fccb, _1)),
                                      std::function<void(const drogon::orm::DrogonDbException &)>(
                                          std::bind(&AdminFilter::onRoleCheckErr, fcb, _1)),
                                      userId);
}

void AdminFilter::onRoleChecked(const HttpRequestPtr &req, FilterCallback fcb,
                                FilterChainCallback fccb, const orm::Result &r) {
    if (r.empty() || r[0]["role"].as<std::string>() != "admin") {
        fcb(ApiResponse::error("需要管理员权限"));
        return;
    }
    fccb(); // 管理员校验通过，放行
}

void AdminFilter::onRoleCheckErr(FilterCallback fcb, const orm::DrogonDbException &e) {
    LOG_ERROR << "AdminFilter role check error: " << e.base().what();
    fcb(ApiResponse::error("internal error"));
}
