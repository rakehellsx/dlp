#pragma once
#include <drogon/HttpController.h>
#include <functional>

// 供 AuthFilter.cc 使用：查库校验 Token（实现在 LoginController.cc）
void validateTokenDb(const std::string &token, std::function<void(bool, int)> callback);

class LoginController : public drogon::HttpController<LoginController> {
  public:
    static constexpr int TOKEN_TTL_SECONDS = 3600 * 24; // Token 有效期 24 小时

    METHOD_LIST_BEGIN
    ADD_METHOD_TO(LoginController::login, "/api/login", drogon::Post);
    ADD_METHOD_TO(LoginController::logout, "/api/logout", drogon::Post, "AuthFilter");
    METHOD_LIST_END

    void login(const drogon::HttpRequestPtr &req,
               std::function<void(const drogon::HttpResponsePtr &)> &&callback);
    void logout(const drogon::HttpRequestPtr &req,
                std::function<void(const drogon::HttpResponsePtr &)> &&callback);

  private:
    using RespCallback = std::function<void(const drogon::HttpResponsePtr &)>;

    // 登录流程各阶段回调（普通成员函数，bind 后传给 execSqlAsync）
    void onLoginQueryOk(std::string clientHash, std::string username, std::string ip,
                        RespCallback callback, const drogon::orm::Result &r);
    void onLoginQueryErr(std::string username, std::string ip, RespCallback callback,
                         const drogon::orm::DrogonDbException &e);
    void onTokenInserted(int userId, std::string username, std::string ip, RespCallback callback,
                         std::string token, const drogon::orm::Result &r);
    void onTokenInsertErr(std::string username, std::string ip, RespCallback callback,
                          const drogon::orm::DrogonDbException &e);

    void onLogoutOk(int operatorId, std::string ip, RespCallback callback,
                    const drogon::orm::Result &r);
    void onLogoutErr(int operatorId, std::string ip, RespCallback callback,
                     const drogon::orm::DrogonDbException &e);
};
