module Theme exposing
    ( Palette
    , editInputWidth
    , gridHeaderHeight
    , modalMaxHeight
    , modalWidth
    , mono
    , palette
    , paletteFor
    , rounded
    , roundedFull
    , roundedMd
    , roundedXl
    , searchBoxWidth
    , sidebarWidth
    , sp05
    , sp1
    , sp15
    , sp2
    , sp25
    , sp3
    , sp4
    , sp5
    , sp8
    , textBase
    , textLg
    , textSm
    , textXs
    , textXxs
    , toolbarHeight
    )

{-| Design tokens for the viewer UI.

If you've used Tailwind, think of this as your `tailwind.config.js` theme —
colors, spacing, typography, and radii defined once and referenced everywhere.
The difference: these are type-checked Elm values, not string class names.
No `bg-blue-500` typos that silently fail.

-}

import Element exposing (Color, rgb255)
import Element.Font as Font



-- SPACING
-- 4px base unit, matching Tailwind's default spacing scale.
-- sp1 = 1 × 4px = Tailwind's `gap-1` / `p-1`
-- sp4 = 4 × 4px = Tailwind's `gap-4` / `p-4`


{-| 2px — Tailwind 0.5. Tiny gaps: badge vertical padding.
-}
sp05 : Int
sp05 =
    2


{-| 4px — Tailwind 1. Compact: icon button padding, small gaps.
-}
sp1 : Int
sp1 =
    4


{-| 6px — Tailwind 1.5. Snug: input vertical padding, list item spacing.
-}
sp15 : Int
sp15 =
    6


{-| 8px — Tailwind 2. Standard small gap: toolbar vertical padding, column gaps.
-}
sp2 : Int
sp2 =
    8


{-| 10px — Tailwind 2.5. Medium: input horizontal padding, toolbar gaps.
-}
sp25 : Int
sp25 =
    10


{-| 12px — Tailwind 3. Comfortable: modal footer padding, section spacing.
-}
sp3 : Int
sp3 =
    12


{-| 16px — Tailwind 4. Generous: sidebar padding, edit bar padding.
-}
sp4 : Int
sp4 =
    16


{-| 20px — Tailwind 5. Roomy: modal body/header padding.
-}
sp5 : Int
sp5 =
    20


{-| 32px — Tailwind 8. Grid line height.
-}
sp8 : Int
sp8 =
    32



-- FONT SIZES
-- Named like Tailwind's text-* scale, but tuned for a dense data UI.
-- Our `textBase` is 13px (not Tailwind's 16px) because table grids
-- need tighter text to show more columns.


{-| 10px — Badges, uppercased section labels.
-}
textXxs : Int
textXxs =
    10


{-| 12px — Buttons, secondary text, status messages.
-}
textXs : Int
textXs =
    12


{-| 14px — Toolbar headings, modal titles.
-}
textSm : Int
textSm =
    14


{-| 13px — Body text, grid cells, sidebar items.

Denser than Tailwind's 16px base because this is a data-heavy UI.

-}
textBase : Int
textBase =
    13


{-| 18px — Toggle icons, close buttons.
-}
textLg : Int
textLg =
    18



-- BORDER RADIUS


{-| 4px — Default radius for small elements (badges, icon buttons).
-}
rounded : Int
rounded =
    4


{-| 6px — Inputs, standard buttons.
-}
roundedMd : Int
roundedMd =
    6


{-| 12px — Modal card.
-}
roundedXl : Int
roundedXl =
    12


{-| 9999px — Pill shape for count badges.
-}
roundedFull : Int
roundedFull =
    9999



-- LAYOUT CONSTANTS
-- Fixed dimensions for structural elements. These don't need to sit on
-- the 4px grid — they're driven by content and visual balance.


sidebarWidth : Int
sidebarWidth =
    230


toolbarHeight : Int
toolbarHeight =
    44


gridHeaderHeight : Int
gridHeaderHeight =
    36


searchBoxWidth : Int
searchBoxWidth =
    200


editInputWidth : Int
editInputWidth =
    300


modalWidth : Int
modalWidth =
    640


modalMaxHeight : Int
modalMaxHeight =
    600



-- COLORS


{-| All the colors the UI needs, in one record.

Like a Tailwind `colors` config but as a typed record — you can't
reference a color that doesn't exist.

-}
type alias Palette =
    { bg : Color
    , sidebarBg : Color
    , sidebarActive : Color
    , sidebarHover : Color
    , text : Color
    , textDim : Color
    , textFaint : Color
    , border : Color
    , accent : Color
    , accentLight : Color
    , success : Color
    , error : Color
    , inputBg : Color
    , inputBorder : Color
    , badgeBg : Color
    , badgeText : Color
    , white : Color
    , editableBg : Color
    , editableText : Color
    }


{-| Select palette based on dark mode preference.
-}
paletteFor : Bool -> Palette
paletteFor darkMode =
    if darkMode then
        darkPalette

    else
        palette


{-| Light palette matching the original viewer CSS variables.
-}
palette : Palette
palette =
    { bg = rgb255 250 250 250
    , sidebarBg = rgb255 240 240 240
    , sidebarActive = rgb255 224 224 224
    , sidebarHover = rgb255 232 232 232
    , text = rgb255 26 26 26
    , textDim = rgb255 136 136 136
    , textFaint = rgb255 170 170 170
    , border = rgb255 221 221 221
    , accent = rgb255 37 99 235
    , accentLight = rgb255 219 234 254
    , success = rgb255 22 163 74
    , error = rgb255 220 38 38
    , inputBg = rgb255 255 255 255
    , inputBorder = rgb255 204 204 204
    , badgeBg = rgb255 229 231 235
    , badgeText = rgb255 107 114 128
    , white = rgb255 255 255 255
    , editableBg = rgb255 220 252 231
    , editableText = rgb255 22 101 52
    }


{-| Dark palette matching the classic viewer's dark CSS variables.
-}
darkPalette : Palette
darkPalette =
    { bg = rgb255 26 26 26
    , sidebarBg = rgb255 34 34 34
    , sidebarActive = rgb255 51 51 51
    , sidebarHover = rgb255 42 42 42
    , text = rgb255 229 229 229
    , textDim = rgb255 119 119 119
    , textFaint = rgb255 85 85 85
    , border = rgb255 51 51 51
    , accent = rgb255 96 165 250
    , accentLight = rgb255 30 58 95
    , success = rgb255 74 222 128
    , error = rgb255 248 113 113
    , inputBg = rgb255 42 42 42
    , inputBorder = rgb255 68 68 68
    , badgeBg = rgb255 55 65 81
    , badgeText = rgb255 156 163 175
    , white = rgb255 255 255 255
    , editableBg = rgb255 20 83 45
    , editableText = rgb255 134 239 172
    }


{-| Monospace font stack for table names and code.

Like Tailwind's `font-mono` utility, but as an Elm value you pass
to `Font.family`.

-}
mono : List Font.Font
mono =
    [ Font.typeface "SF Mono"
    , Font.typeface "Fira Code"
    , Font.typeface "Consolas"
    , Font.monospace
    ]
