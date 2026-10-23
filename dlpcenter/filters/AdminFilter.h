#pragma once
#include <drogon/HttpFilter.h>
#include <drogon/drogon.h>

// 管理员权限过滤器：在 AuthFilter（登录态）基础上，额外校验 role='admin'
class AdminFilter : public drogon::HttpFilter<AdminFilter> {
  public:
    AdminFilter() = default;
    void doFilter(const drogon::HttpRequestPtr &req, drogon::FilterCallback &&fcb,
                  drogon::FilterChainCallback &&fccb) override;

  private:
    // Token 校验完成后的处理
    static void onTokenChecked(const drogon::HttpRequestPtr &req, drogon::FilterCallback fcb,
                               drogon::FilterChainCallback fccb, bool ok, int userId);
    // 角色查询完成后的处理
    static void onRoleChecked(const drogon::HttpRequestPtr &req, drogon::FilterCallback fcb,
                              drogon::FilterChainCallback fccb, const drogon::orm::Result &r);
    static void onRoleCheckErr(drogon::FilterCallback fcb, const drogon::orm::DrogonDbException &e);
};
