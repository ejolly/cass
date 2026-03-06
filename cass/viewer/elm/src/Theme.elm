module Theme exposing
    ( Palette
    , mono
    , palette
    , paletteFor
    , sidebarWidth
    )

{-| Design tokens for the viewer UI.

If you've used Tailwind, think of this as your `tailwind.config.js` theme —
colors, spacing, and typography defined once and referenced everywhere.
The difference: these are type-checked Elm values, not string class names.
No `bg-blue-500` typos that silently fail.

-}

import Element exposing (Color, rgb255)
import Element.Font as Font


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


sidebarWidth : Int
sidebarWidth =
    230
