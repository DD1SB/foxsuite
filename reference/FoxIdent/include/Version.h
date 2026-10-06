/******************************************************************************
 *  Project : FoxIdent
 *  File    : Version.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <cstdint>

namespace Fox
{

    struct Version
    {
        static constexpr std::uint8_t Major = 1U;
        static constexpr std::uint8_t Minor = 0U;
        static constexpr std::uint8_t Patch = 0U;

        static constexpr char Name[] = "FoxStation";
    };

} // namespace Fox