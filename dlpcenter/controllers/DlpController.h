#pragma once
#include <drogon/HttpController.h>
class DlpController : public drogon::HttpController<DlpController> {
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(DlpController::handle, "/health", drogon::Get);
    ADD_METHOD_TO(DlpController::handle, "/api/bootstrap", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/export", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/query", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/statistics", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/search", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/detail", drogon::Get, "AuthFilter");

    ADD_METHOD_TO(DlpController::image, "/api/watermark-image/{1}", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/save", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/update", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/delete", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/scan", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/detect", drogon::Post, "AuthFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/settings", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/report", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/watermark-images/import", drogon::Post,
                  "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/watermark-images/save", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/watermark-images/delete", drogon::Post,
                  "AdminFilter");
    ADD_METHOD_TO(DlpController::handle, "/api/watermark-images/ocr", drogon::Post, "AdminFilter");
    METHOD_LIST_END
    void handle(const drogon::HttpRequestPtr &,
                std::function<void(const drogon::HttpResponsePtr &)> &&);
    void image(const drogon::HttpRequestPtr &,
               std::function<void(const drogon::HttpResponsePtr &)> &&, std::string);
};
