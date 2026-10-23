#include "AuthFilter.h"
#include "controllers/LoginController.h" // validateTokenDb 声明
#include "utils/ApiResponse.h"
#include "utils/AuthToken.h"
#include <drogon/drogon.h>

using namespace drogon;
using std::placeholders::_1;
using std::placeholders::_2;

void AuthFilter::doFilter(const HttpRequestPtr &req, FilterCallback &&fcb,
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

    // 异步查库校验；bind 绑定 req 和回调，由静态函数处理结果
    validateTokenDb(token, std::bind(&AuthFilter::onTokenChecked, req, std::move(fcb),
                                     std::move(fccb), _1, _2));
}

void AuthFilter::onTokenChecked(const HttpRequestPtr &req, FilterCallback fcb,
                                FilterChainCallback fccb, bool ok, int userId) {
    if (ok) {
        req->attributes()->insert("userId", userId); // 传给后续 Controller
        fccb();                                      // 放行
    } else {
        fcb(ApiResponse::error("未登录或Token已过期"));
    }
}
