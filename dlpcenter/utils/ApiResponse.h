#pragma once
#include <drogon/HttpResponse.h>

// ============================================================
// 统一响应约定：
//   - 所有接口一律返回 HTTP 200（成功与失败都是）
//   - body 通过 code 字段区分结果：
//       成功: {"code":0, ...业务数据}
//       失败: {"code":1, "error":"失败原因"}
//   - 响应头 X-Err-Code: 0/1，失败时附带 X-Err-Msg
//     （供 Nginx/监控/网关等基础设施识别，不解析 body 即可判断成败）
// ============================================================
class ApiResponse {
  public:
    // 成功：仅返回 code
    static drogon::HttpResponsePtr ok() {
        Json::Value v;
        v["code"] = 0;
        return build(v);
    }

    // 成功：业务数据 + 自动补 code=0
    static drogon::HttpResponsePtr ok(const Json::Value &data) {
        Json::Value v = data;
        v["code"] = 0;
        return build(v);
    }

    // 失败：body 带错误信息 + 失败响应头
    static drogon::HttpResponsePtr error(const std::string &msg) {
        Json::Value v;
        v["code"] = 1;
        v["error"] = msg;
        auto resp = build(v);
        resp->addHeader("X-Err-Code", "1"); // addHeader 对已存在的 key 是覆盖
        resp->addHeader("X-Err-Msg", msg);
        return resp;
    }

  private:
    static drogon::HttpResponsePtr build(const Json::Value &v) {
        auto resp = drogon::HttpResponse::newHttpJsonResponse(v);
        resp->addHeader("X-Err-Code", "0");
        resp->addHeader("Cache-Control", "no-store");
        resp->addHeader("X-Content-Type-Options", "nosniff");
        return resp;
    }
};
