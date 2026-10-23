#pragma once
#include <drogon/HttpRequest.h>
#include <string>

// ============================================================
// 操作审计日志：异步写入 operation_logs 表，fire-and-forget，
// 写日志失败只记服务端错误日志，不影响主业务流程。
//
//   operatorId : 操作人用户ID，未登录/未知时传 0
//                （operator_name 由 SQL 子查询按 users 表自动回填，回填不到为 NULL）
//   action     : 动作标识，如 login / logout / create / delete / disable / enable / change_password
//   target     : 操作目标，如被操作用户名（无目标可传空串）
//   detail     : 补充说明（建议 JSON 字符串，可为空）
//   ip         : 客户端 IP，用 clientIp(req) 获取
//   success    : 操作是否成功
// ============================================================
void auditLog(int operatorId, const std::string &action, const std::string &target,
              const std::string &detail, const std::string &ip, bool success);

// 获取客户端 IP：优先取 X-Forwarded-For 第一个地址（兼容 Nginx 反向代理），
// 否则取对端地址。
inline std::string clientIp(const drogon::HttpRequestPtr &req) {
    auto xff = req->getHeader("X-Forwarded-For");
    if (!xff.empty()) {
        auto pos = xff.find(',');
        return pos == std::string::npos ? xff : xff.substr(0, pos);
    }
    return req->peerAddr().toIp();
}
