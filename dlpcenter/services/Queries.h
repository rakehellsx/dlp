#pragma once
#include "Pg.h"
namespace dlp {
Json::Value listRecords(Pg &, const std::string &, const Json::Value &, bool exportAll = false);
Json::Value statistics(Pg &, int days = 7, int chartDays = 7);
Json::Value lookups(Pg &);
Json::Value recordDetail(Pg &, const std::string &, const std::string &);
Json::Value reportSnapshot(Pg &, int);
void advanceScans(Pg &);
} // namespace dlp
