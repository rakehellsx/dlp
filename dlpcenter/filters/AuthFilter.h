#pragma once
#include <drogon/HttpFilter.h>

class AuthFilter : public drogon::HttpFilter<AuthFilter> {
  public:
    AuthFilter() = default;
    void doFilter(const drogon::HttpRequestPtr &req, drogon::FilterCallback &&fcb,
                  drogon::FilterChainCallback &&fccb) override;

  private:
    // Token 校验完成后的处理（静态函数，bind 传入请求上下文）
    static void onTokenChecked(const drogon::HttpRequestPtr &req, drogon::FilterCallback fcb,
                               drogon::FilterChainCallback fccb, bool ok, int userId);
};
