# Elm Viewer Walkthrough

*2026-03-06T05:27:03Z by Showboat 0.6.1*
<!-- showboat-id: 1b271d6e-41f3-44dc-be9b-6b415168bba6 -->

## Overview

The cass database viewer is an Elm 0.19.1 single-page app that displays DuckDB tables in a browser. It uses **elm-ui** for layout/styling and **elm-advanced-grid** for the data table.

If you're used to building UIs with **Svelte + Tailwind**, here's the quick mental map:

| Svelte + Tailwind | Elm |
|---|---|
| `.svelte` component files | `.elm` module files |
| Reactive `$state` / `let` variables | `Model` record (all state in one place) |
| `on:click`, `bind:value` | `Msg` union type (all events in one type) |
| `onMount` / `$effect` | `Cmd` values returned from `update` |
| Tailwind utility classes (`flex gap-4 p-4`) | elm-ui attributes (`row [ spacing 16, padding 16 ]`) |
| `+page.ts` load functions | `Http.get` returning `Cmd Msg` |
| Stores / context | Just pass data as function arguments |

The key difference: in Svelte, state mutations are implicit (reassign a variable and the UI reacts). In Elm, every state change is an explicit `case` branch in `update` — nothing happens behind your back.

## Project structure

The Elm source lives in `elm/src/` — five modules, each with a clear responsibility. Compare this to a Svelte project where you'd have `+page.svelte`, `+page.ts`, a few component files, and maybe a `stores.ts`.

```bash
ls -1 elm/src/*.elm
```

```output
elm/src/Api.elm
elm/src/Main.elm
elm/src/Theme.elm
elm/src/Types.elm
elm/src/View.elm
```

| Module | Lines | Role | Svelte equivalent |
|--------|-------|------|-------------------|
| `Types.elm` | ~90 | All type definitions | `types.ts` — your interfaces and discriminated unions |
| `Theme.elm` | ~90 | Colors, fonts, sizing | `tailwind.config.js` — design tokens, but type-checked |
| `Api.elm` | ~190 | HTTP + JSON decoders | `+page.ts` loader / `fetch` calls in `onMount` |
| `View.elm` | ~490 | All view functions (elm-ui) | Your `.svelte` component files + Tailwind classes |
| `Main.elm` | ~160 | TEA wiring (init, update) | `+page.svelte` script block — state + event handlers |

## 1. Types — the single source of truth

In Svelte + TypeScript, you'd define interfaces in `types.ts`. In Elm, `Types.elm` serves the same role — but with one big addition: the `Msg` type. This is a union type that lists **every possible event** in the app. The compiler guarantees you handle all of them.

In Svelte, events are scattered: `on:click` handlers, store subscriptions, fetch callbacks. In Elm, they all flow through `Msg`.

```bash
cat elm/src/Types.elm
```

```output
module Types exposing
    ( ColumnSchema
    , Model
    , Msg(..)
    , Row
    , TableData
    , TableInfo
    , TableSchema
    )

{-| All types for the viewer app, gathered in one module.

In Svelte you'd define TypeScript interfaces in a `types.ts` file.
In Elm, a `Types.elm` module serves the same role — single source of
truth for every data shape in the app.

Key difference from TS: Elm's `type` (union type) is exhaustively
checked at compile time. The `Msg` type below is the equivalent of
a discriminated union for all possible events.

-}

import Dict exposing (Dict)
import Grid
import Http
import Json.Decode as D


type alias TableInfo =
    { name : String
    , tableType : String
    }


type alias TableSchema =
    { table : String
    , columns : List ColumnSchema
    , primaryKeys : List String
    , editable : Bool
    , canvasPushable : List String
    }


type alias ColumnSchema =
    { name : String
    , colType : String
    , nullable : Bool
    }


type alias TableData =
    { table : String
    , columns : List String
    , types : List String
    , rows : List (List D.Value)
    }


{-| A row is a Dict from column name to string value.

We normalize everything to strings for display in the grid.
Similar to how AG Grid in JS works with `rowData` arrays of objects.

-}
type alias Row =
    { values : Dict String String }


type alias Model =
    { tables : List TableInfo
    , selectedTable : Maybe String
    , schema : Maybe TableSchema
    , rows : List Row
    , gridModel : Maybe (Grid.Model Row)
    , searchText : String
    , sidebarCollapsed : Bool
    , error : Maybe String
    }


{-| Every possible event in the app.

In Svelte, events are scattered: on:click handlers, dispatched events,
store subscriptions. In Elm, ALL events flow through this single type.
The compiler guarantees you handle every variant in `update`.

-}
type Msg
    = GotTables (Result Http.Error (List TableInfo))
    | SelectTable String
    | GotSchemaAndData String (Result Http.Error ( TableSchema, TableData ))
    | GridMsg (Grid.Msg Row)
    | SearchChanged String
    | ToggleSidebar
```

Notice the `Model` type — it holds ALL application state in one record. In Svelte, you'd have `let tables = []`, `let selectedTable = null`, etc. scattered across your script block. In Elm, it's a single typed record. No `$state` rune, no reactive declarations — just data.

The `Msg` type is like a TypeScript discriminated union: `type AppEvent = { kind: 'GotTables', data: TableInfo[] } | { kind: 'SelectTable', name: string } | ...`. But Elm enforces exhaustive handling at compile time — miss a case and it won't compile.

## 2. Theme — design tokens as typed values

In Tailwind, your design system lives in `tailwind.config.js` as strings: `colors.blue.500 = '#2563eb'`. In elm-ui, it's a typed `Palette` record. You can't reference `p.bleu` (typo) — the compiler catches it. No more silent CSS class typos.

```bash
cat elm/src/Theme.elm
```

```output
module Theme exposing
    ( Palette
    , mono
    , palette
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


{-| Default palette matching the original viewer CSS variables.
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
```

## 3. Main — the TEA core

This is where The Elm Architecture (TEA) lives. In Svelte terms, think of this as your `+page.svelte` script block — but with a rigid structure:

- **`init`** = `onMount` — runs once, returns initial state + first command
- **`update`** = your event handlers — but ALL of them in one function, pattern-matched on `Msg`
- **`view`** = the template — but delegated to `View.elm`
- **`subscriptions`** = like Svelte stores that push values to you (unused here)

The critical insight: `update` returns `( Model, Cmd Msg )` — the new state AND any side effects. You never mutate state. You never call `fetch` imperatively. You describe what should happen, and the runtime does it.

```bash
cat elm/src/Main.elm
```

```output
module Main exposing (main)

{-| cass database viewer — Elm frontend with elm-ui.

This is the TEA (The Elm Architecture) core: init, update, subscriptions.
All view code lives in View.elm, HTTP/decoding in Api.elm.

**TEA vs Svelte mental model:**

In Svelte, state lives in reactive variables (`let count = 0`), events
are inline handlers (`on:click`), and effects happen in `onMount` or
`$effect`. State mutations are implicit — just reassign the variable.

In Elm, ALL state lives in `Model`, ALL events are `Msg` variants,
and ALL effects are returned as `Cmd` values from `update`. Nothing
happens behind your back — every state transition is an explicit
`case` branch. This makes debugging trivial: log any `Msg` and you
can replay the entire app history.

-}

import Api
import Browser
import Dict
import Grid
import Types exposing (..)
import View


main : Program () Model Msg
main =
    Browser.element
        { init = init
        , view = View.view
        , update = update
        , subscriptions = \_ -> Sub.none
        }


init : () -> ( Model, Cmd Msg )
init _ =
    ( { tables = []
      , selectedTable = Nothing
      , schema = Nothing
      , rows = []
      , gridModel = Nothing
      , searchText = ""
      , sidebarCollapsed = False
      , error = Nothing
      }
    , Api.fetchTables
    )


{-| Handle every event in the app.

This is the heart of TEA. Each Msg variant maps to exactly one branch.
In Svelte, these would be scattered across on:click handlers, store
subscribers, and fetch callbacks. Here, they're all in one place —
easy to read top-to-bottom and reason about.

-}
update : Msg -> Model -> ( Model, Cmd Msg )
update msg model =
    case msg of
        GotTables result ->
            case result of
                Ok tables ->
                    let
                        firstTable =
                            List.head tables |> Maybe.map .name
                    in
                    ( { model | tables = tables }
                    , case firstTable of
                        Just name ->
                            Api.fetchSchemaAndData name

                        Nothing ->
                            Cmd.none
                    )

                Err err ->
                    ( { model | error = Just (Api.httpErrorToString err) }, Cmd.none )

        SelectTable name ->
            if model.selectedTable == Just name then
                ( model, Cmd.none )

            else
                ( { model
                    | selectedTable = Just name
                    , searchText = ""
                    , error = Nothing
                    , gridModel = Nothing
                  }
                , Api.fetchSchemaAndData name
                )

        GotSchemaAndData name result ->
            case result of
                Ok ( schema, tableData ) ->
                    let
                        rows =
                            Api.parseRows tableData

                        gridModel =
                            View.initGrid tableData.columns tableData.types name rows
                    in
                    ( { model
                        | selectedTable = Just name
                        , schema = Just schema
                        , rows = rows
                        , gridModel = Just gridModel
                        , error = Nothing
                      }
                    , Cmd.none
                    )

                Err err ->
                    ( { model | error = Just (Api.httpErrorToString err) }, Cmd.none )

        GridMsg gridMsg ->
            case model.gridModel of
                Just gm ->
                    let
                        ( newGridModel, gridCmd ) =
                            Grid.update gridMsg gm
                    in
                    ( { model | gridModel = Just newGridModel }
                    , Cmd.map GridMsg gridCmd
                    )

                Nothing ->
                    ( model, Cmd.none )

        SearchChanged newText ->
            case model.gridModel of
                Just gm ->
                    let
                        filters =
                            if String.isEmpty newText then
                                Dict.empty

                            else
                                model.schema
                                    |> Maybe.map .columns
                                    |> Maybe.withDefault []
                                    |> List.map (\c -> ( c.name, newText ))
                                    |> Dict.fromList

                        ( newGridModel, gridCmd ) =
                            Grid.update (Grid.SetFilters filters) gm
                    in
                    ( { model | searchText = newText, gridModel = Just newGridModel }
                    , Cmd.map GridMsg gridCmd
                    )

                Nothing ->
                    ( { model | searchText = newText }, Cmd.none )

        ToggleSidebar ->
            ( { model | sidebarCollapsed = not model.sidebarCollapsed }, Cmd.none )
```

Key patterns to notice:

- **Record update syntax**: `{ model | tables = tables }` — like the spread operator in Svelte (`{...state, tables}`) but the compiler ensures every field exists.
- **`Cmd.none`** — "no side effects." Like returning nothing from an event handler. Most branches return this.
- **`Cmd.map GridMsg`** — wraps a sub-component's commands. The grid library has its own `Msg` type; `Cmd.map` tags its events so they flow through our `GridMsg` variant. In Svelte, you'd use `createEventDispatcher` or `$bindable` for parent-child communication.
- **Pattern matching on `Result`** — `Ok data` or `Err error`. No try/catch, no `.then().catch()`. The compiler forces you to handle both.

## 4. Api — HTTP and JSON decoding

In SvelteKit, data fetching lives in `+page.ts` loaders or `onMount` calls with `fetch`. In Elm, HTTP is a side effect — you describe the request, return it as a `Cmd`, and the runtime executes it. The result arrives as a `Msg`.

JSON decoding is also different. In JavaScript, `response.json()` gives you an untyped `any`. In Elm, you build explicit decoders that parse JSON into typed values — if the shape doesn't match, you get an `Err`, not a runtime crash.

```bash
cat elm/src/Api.elm
```

```output
module Api exposing
    ( fetchSchemaAndData
    , fetchTables
    , httpErrorToString
    , parseRows
    )

{-| HTTP requests and JSON decoders for the viewer API.

In Svelte you'd use `fetch` in a `+page.ts` loader or an `onMount`.
In Elm, HTTP is a side effect — you return a `Cmd` from `update` and
the runtime executes it, calling you back with the result as a `Msg`.
No `async/await`, no `try/catch` — just data in, data out.

-}

import Dict
import Http
import Json.Decode as D
import Task
import Types exposing (..)


fetchTables : Cmd Msg
fetchTables =
    Http.get
        { url = "/api/tables"
        , expect = Http.expectJson GotTables tablesDecoder
        }


{-| Fetch schema and data in parallel, then combine into a tuple.

In Svelte/JS you'd do `Promise.all([fetchSchema(), fetchData()])`.
In Elm, `Task.map2` is the equivalent — it runs two tasks and combines
their results. If either fails, you get the first error.

-}
fetchSchemaAndData : String -> Cmd Msg
fetchSchemaAndData name =
    let
        schemaTask =
            Http.task
                { method = "GET"
                , headers = []
                , url = "/api/schema/" ++ name
                , body = Http.emptyBody
                , resolver = Http.stringResolver (resolveJson schemaDecoder)
                , timeout = Nothing
                }

        dataTask =
            Http.task
                { method = "GET"
                , headers = []
                , url = "/api/table/" ++ name
                , body = Http.emptyBody
                , resolver = Http.stringResolver (resolveJson tableDataDecoder)
                , timeout = Nothing
                }
    in
    Task.map2 Tuple.pair schemaTask dataTask
        |> Task.attempt (GotSchemaAndData name)


resolveJson : D.Decoder a -> Http.Response String -> Result Http.Error a
resolveJson decoder response =
    case response of
        Http.BadUrl_ url ->
            Err (Http.BadUrl url)

        Http.Timeout_ ->
            Err Http.Timeout

        Http.NetworkError_ ->
            Err Http.NetworkError

        Http.BadStatus_ metadata _ ->
            Err (Http.BadStatus metadata.statusCode)

        Http.GoodStatus_ _ body ->
            case D.decodeString decoder body of
                Ok val ->
                    Ok val

                Err err ->
                    Err (Http.BadBody (D.errorToString err))



-- DECODERS


tablesDecoder : D.Decoder (List TableInfo)
tablesDecoder =
    D.field "tables"
        (D.list
            (D.map2 TableInfo
                (D.field "name" D.string)
                (D.field "type" D.string)
            )
        )


schemaDecoder : D.Decoder TableSchema
schemaDecoder =
    D.map5 TableSchema
        (D.field "table" D.string)
        (D.field "columns"
            (D.list
                (D.map3 ColumnSchema
                    (D.field "name" D.string)
                    (D.field "type" D.string)
                    (D.field "nullable" D.bool)
                )
            )
        )
        (D.field "primary_keys" (D.list D.string))
        (D.field "editable" D.bool)
        (D.field "canvas_pushable" (D.list D.string))


tableDataDecoder : D.Decoder TableData
tableDataDecoder =
    D.map4 TableData
        (D.field "table" D.string)
        (D.field "columns" (D.list D.string))
        (D.field "types" (D.list D.string))
        (D.field "rows" (D.list (D.list D.value)))



-- DATA PARSING


parseRows : TableData -> List Row
parseRows tableData =
    List.map
        (\rawRow ->
            let
                pairs =
                    List.map2
                        (\colName val -> ( colName, jsonValueToString val ))
                        tableData.columns
                        rawRow
            in
            Row (Dict.fromList pairs)
        )
        tableData.rows


jsonValueToString : D.Value -> String
jsonValueToString val =
    case D.decodeValue D.string val of
        Ok s ->
            s

        Err _ ->
            case D.decodeValue D.float val of
                Ok f ->
                    if f == toFloat (round f) && abs f < 1.0e10 then
                        String.fromInt (round f)

                    else
                        String.fromFloat f

                Err _ ->
                    case D.decodeValue D.bool val of
                        Ok True ->
                            "Yes"

                        Ok False ->
                            "No"

                        Err _ ->
                            ""


httpErrorToString : Http.Error -> String
httpErrorToString err =
    case err of
        Http.BadUrl url ->
            "Bad URL: " ++ url

        Http.Timeout ->
            "Request timed out"

        Http.NetworkError ->
            "Network error"

        Http.BadStatus status ->
            "Server error: " ++ String.fromInt status

        Http.BadBody body ->
            "Bad response: " ++ body
```

The decoder pattern takes getting used to. In Svelte/TS you'd just type `const data: TableInfo[] = await res.json()` and hope the shape matches. In Elm, `D.map2 TableInfo (D.field "name" D.string) (D.field "type" D.string)` explicitly says: "parse a JSON object, extract the `name` and `type` fields as strings, and construct a `TableInfo`." If the JSON doesn't match, you get a clean error instead of `undefined is not a function` at runtime.

`Task.map2 Tuple.pair` is Elm's `Promise.all` — it runs two HTTP requests and combines the results into a tuple `(schema, data)`. If either fails, the whole thing fails with the first error.

## 5. View — elm-ui layout (the big one)

This is where the Tailwind mental model helps most. elm-ui is like Tailwind but without strings — every "utility class" is a typed function.

Here's the cheat sheet:

| Tailwind | elm-ui |
|---|---|
| `flex flex-row` | `row [ ... ]` |
| `flex flex-col` | `column [ ... ]` |
| `w-full` | `width fill` |
| `h-full` | `height fill` |
| `w-[200px]` | `width (px 200)` |
| `gap-4` | `spacing 16` (on the parent!) |
| `p-4` | `padding 16` |
| `px-4 py-2` | `paddingXY 16 8` |
| `bg-blue-500` | `Background.color p.accent` |
| `text-sm` | `Font.size 13` |
| `font-bold` | `Font.bold` |
| `rounded-md` | `Border.rounded 6` |
| `border-b` | `Border.widthEach { bottom = 1, ... }` |
| `hover:bg-gray-200` | `mouseOver [ Background.color p.sidebarHover ]` |
| `focus:ring-2` | `focused [ Border.shadow { ... } ]` |
| `ml-auto` | `alignRight` |
| `overflow-y-auto` | `scrollbarY` |
| `items-center justify-center` | `centerX, centerY` |
| `hidden` / `{#if false}` | `none` |

```bash
cat elm/src/View.elm
```

```output
module View exposing (initGrid, view)

{-| All view code for the viewer, written with elm-ui.

If you're coming from Svelte + Tailwind, here's the mental model shift:

**Tailwind:** You write HTML, then attach utility classes as strings.
<div class="flex flex-col gap-4 p-4 bg-gray-100">

**elm-ui:** You call layout functions, passing attributes as a list.
column [ spacing 16, padding 16, Background.color gray100 ][ ... ]

The key differences:

1.  No CSS file at all — styles live next to the elements they affect
    (like Tailwind, but without the string indirection)
2.  Layout is explicit: `row` = horizontal, `column` = vertical
    (replaces `flex`, `flex-row`, `flex-col`)
3.  Sizing is explicit: `width fill` = `w-full`, `width (px 200)` = `w-[200px]`
4.  Spacing belongs to the PARENT, not the children
    (`spacing 8` on a column = `gap-2` in Tailwind)
5.  No cascading, no specificity wars — each element owns its styles

In Svelte terms: imagine if every component's styles were guaranteed
scoped, co-located, and type-checked. That's elm-ui.

-}

import Dict exposing (Dict)
import Element exposing (..)
import Element.Background as Background
import Element.Border as Border
import Element.Font as Font
import Element.Input as Input
import Grid exposing (ColumnConfig)
import Html
import Theme exposing (Palette)
import Types exposing (..)



-- PUBLIC API


{-| Top-level view function. Returns Html (not Element) because
Browser.element expects `view : Model -> Html Msg`.

`Element.layout` is the bridge — it wraps the entire elm-ui tree
in a single DOM node. Think of it as Svelte's `<svelte:body>` or
the root `<div id="app">` that your Tailwind styles hang off of.

-}
view : Model -> Html.Html Msg
view model =
    let
        p =
            Theme.palette
    in
    layout
        [ width fill
        , height fill
        , Font.family
            [ Font.typeface "-apple-system"
            , Font.typeface "BlinkMacSystemFont"
            , Font.typeface "Segoe UI"
            , Font.typeface "Roboto"
            , Font.sansSerif
            ]
        , Font.size 13
        , Font.color p.text
        , Background.color p.bg
        ]
        (row [ width fill, height fill ]
            [ viewSidebar p model
            , viewMain p model
            ]
        )



-- SIDEBAR
-- In Svelte, this would be a <Sidebar> component with props.
-- In Elm, it's just a function. No component lifecycle, no slots,
-- no context API — just `Palette -> Model -> Element Msg`.


viewSidebar : Palette -> Model -> Element Msg
viewSidebar p model =
    if model.sidebarCollapsed then
        -- `none` = render nothing. Like Svelte's `{#if false}` block.
        none

    else
        column
            [ width (px Theme.sidebarWidth)
            , height fill
            , Background.color p.sidebarBg
            , Border.widthEach { bottom = 0, left = 0, right = 1, top = 0 }
            , Border.color p.border

            -- scrollbarY = Tailwind's `overflow-y-auto`
            , scrollbarY
            ]
            [ viewSidebarHeader p
            , column [ width fill, paddingEach { top = 4, right = 0, bottom = 4, left = 0 } ]
                (viewTableGroups p model)
            ]


viewSidebarHeader : Palette -> Element Msg
viewSidebarHeader p =
    row
        [ width fill
        , paddingXY 16 12
        , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
        , Border.color p.border
        ]
        [ el
            [ Font.size 15
            , Font.bold
            , Font.color p.textDim
            , Font.letterSpacing 0.8
            ]
            (text "CASS")

        -- alignRight pushes this button to the right edge.
        -- In Tailwind: `ml-auto`. In Svelte: `style="margin-left: auto"`.
        , Input.button
            [ alignRight
            , Font.size 18
            , Font.color p.textDim
            , padding 4
            , Border.rounded 4
            , mouseOver [ Background.color p.sidebarActive ]
            ]
            { onPress = Just ToggleSidebar
            , label = text "‹"
            }
        ]


viewTableGroups : Palette -> Model -> List (Element Msg)
viewTableGroups p model =
    let
        canvas =
            List.filter (\t -> String.startsWith "canvas_" t.name) model.tables

        github =
            List.filter (\t -> String.startsWith "gh_" t.name) model.tables

        master =
            List.filter
                (\t ->
                    not (String.startsWith "canvas_" t.name)
                        && not (String.startsWith "gh_" t.name)
                )
                model.tables

        viewGroup label items =
            if List.isEmpty items then
                []

            else
                [ column [ width fill, paddingEach { top = 0, right = 0, bottom = 4, left = 0 } ]
                    (el
                        [ Font.size 10
                        , Font.semiBold
                        , Font.color p.textDim
                        , Font.letterSpacing 0.6
                        , paddingEach { top = 14, right = 16, bottom = 4, left = 16 }
                        ]
                        (text (String.toUpper label))
                        :: List.map (viewTableItem p model.selectedTable) items
                    )
                ]
    in
    viewGroup "Combined Data" master
        ++ viewGroup "Canvas LMS" canvas
        ++ viewGroup "GitHub Classroom" github


viewTableItem : Palette -> Maybe String -> TableInfo -> Element Msg
viewTableItem p selected t =
    let
        isActive =
            selected == Just t.name

        -- Conditional attributes — like Svelte's `class:active={isActive}`
        -- but instead of toggling CSS classes, we swap elm-ui attribute values.
        ( bgAttr, fontColorAttr, hoverAttr ) =
            if isActive then
                ( Background.color p.accent
                , Font.color p.white
                , []
                )

            else
                ( Background.color (rgba 0 0 0 0)
                , Font.color p.text
                , [ mouseOver [ Background.color p.sidebarHover ] ]
                )
    in
    Input.button
        ([ width fill
         , paddingXY 16 7
         , Font.family Theme.mono
         , Font.size 13
         , bgAttr
         , fontColorAttr
         ]
            ++ hoverAttr
        )
        { onPress = Just (SelectTable t.name)
        , label = text t.name
        }



-- MAIN AREA


viewMain : Palette -> Model -> Element Msg
viewMain p model =
    column [ width fill, height fill ]
        [ -- When sidebar is collapsed, show a toggle button overlaid
          -- on the main area. `inFront` = CSS `position: absolute`.
          -- Like Svelte's style:position="absolute" or Tailwind's `absolute`.
          if model.sidebarCollapsed then
            el
                [ inFront (viewSidebarToggle p)
                , width fill
                ]
                none

          else
            none
        , viewToolbar p model
        , viewGridArea p model
        ]


viewSidebarToggle : Palette -> Element Msg
viewSidebarToggle p =
    Input.button
        [ alignLeft
        , moveDown 10
        , moveRight 8
        , padding 4
        , Font.size 18
        , Font.color p.textDim
        , Background.color p.sidebarBg
        , Border.width 1
        , Border.color p.border
        , Border.rounded 4
        , mouseOver [ Background.color p.sidebarActive ]
        ]
        { onPress = Just ToggleSidebar
        , label = text "›"
        }



-- TOOLBAR


viewToolbar : Palette -> Model -> Element Msg
viewToolbar p model =
    -- `row` with `spacing` = Tailwind `flex items-center gap-2.5`
    row
        [ width fill
        , paddingXY 16 8
        , spacing 10
        , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
        , Border.color p.border
        , height (px 44)
        ]
        [ el [ Font.semiBold, Font.size 14 ]
            (text (Maybe.withDefault "" model.selectedTable))
        , viewBadge p model
        , el [ Font.size 12, Font.color p.textDim ]
            (text (rowCountText model))

        -- alignRight on this element pushes it to the far right.
        -- Equivalent to Tailwind's `ml-auto` on a flex child.
        , el [ alignRight ] (viewSearchBox p model)
        ]


viewBadge : Palette -> Model -> Element Msg
viewBadge p model =
    case model.schema of
        Just schema ->
            let
                ( label, bgColor, textColor ) =
                    if schema.editable then
                        ( "EDITABLE", p.editableBg, p.editableText )

                    else
                        ( "READ-ONLY", p.badgeBg, p.badgeText )
            in
            el
                [ Font.size 10
                , Font.semiBold
                , Font.letterSpacing 0.3
                , Font.color textColor
                , Background.color bgColor
                , paddingXY 7 2
                , Border.rounded 4
                ]
                (text label)

        Nothing ->
            none


viewSearchBox : Palette -> Model -> Element Msg
viewSearchBox p model =
    -- elm-ui's Input.text replaces <input type="text">.
    -- In Svelte: <input bind:value={searchText} on:input={handleSearch}>
    -- In elm-ui: the `onChange` is baked into the Input.text config.
    Input.text
        [ width (px 200)
        , Font.size 13
        , paddingXY 10 5
        , Border.width 1
        , Border.color p.inputBorder
        , Border.rounded 6
        , Background.color p.inputBg
        , Font.color p.text
        , focused
            [ Border.color p.accent
            , Border.shadow
                { offset = ( 0, 0 )
                , size = 2
                , blur = 0
                , color = p.accentLight
                }
            ]
        ]
        { onChange = SearchChanged
        , text = model.searchText
        , placeholder =
            Just
                (Input.placeholder [ Font.color p.textFaint ]
                    (text "Search rows...")
                )
        , label = Input.labelHidden "Search rows"
        }



-- GRID AREA


viewGridArea : Palette -> Model -> Element Msg
viewGridArea p model =
    case model.gridModel of
        Just gm ->
            -- `Element.html` bridges elm/html into elm-ui.
            -- The grid library renders standard Html; we wrap it
            -- so it lives inside our elm-ui layout.
            -- Like using {@html rawContent} in Svelte, but type-safe.
            el [ width fill, height fill, clip ]
                (Grid.view gm
                    |> Html.map GridMsg
                    |> html
                )

        Nothing ->
            case model.error of
                Just err ->
                    -- centerX + centerY = Tailwind `flex items-center justify-center`
                    el [ centerX, centerY, Font.color p.error ]
                        (text err)

                Nothing ->
                    el [ centerX, centerY, Font.color p.textDim ]
                        (text "Select a table from the sidebar")


rowCountText : Model -> String
rowCountText model =
    let
        count =
            List.length model.rows

        colCount =
            model.schema
                |> Maybe.map (.columns >> List.length)
                |> Maybe.withDefault 0
    in
    if count > 0 then
        String.fromInt count ++ " rows · " ++ String.fromInt colCount ++ " columns"

    else
        ""



-- GRID INITIALIZATION
-- Called from Main.update when table data arrives.


{-| Columns to hide for specific tables (internal IDs that clutter the view).
-}
hiddenColumns : Dict String (List String)
hiddenColumns =
    Dict.fromList
        [ ( "canvas_assignments", [ "canvas_id" ] )
        , ( "canvas_students", [ "canvas_id" ] )
        , ( "canvas_submissions", [ "canvas_user_id", "canvas_assignment_id" ] )
        , ( "canvas_grades", [ "canvas_user_id", "canvas_assignment_id" ] )
        ]


{-| Build grid config and initialize the grid model.

Separated from the view so Main.update can call it when data arrives.
The grid library needs its dimensions at init time (like AG Grid's
`domLayout` or `containerStyle` props in the JS world).

-}
initGrid : List String -> List String -> String -> List Row -> Grid.Model Row
initGrid colNames colTypes tableName rows =
    let
        columns =
            buildGridColumns colNames colTypes tableName

        gridConfig : Grid.Config Row
        gridConfig =
            { canSelectRows = False
            , columns = columns
            , containerHeight = 800
            , containerWidth = 1200
            , hasFilters = True
            , headerHeight = 60
            , lineHeight = 32
            , rowClass = \_ -> ""
            }
    in
    Grid.init gridConfig rows


buildGridColumns : List String -> List String -> String -> List (ColumnConfig Row)
buildGridColumns colNames colTypes tableName =
    let
        hidden =
            Dict.get tableName hiddenColumns |> Maybe.withDefault []
    in
    colNames
        |> List.indexedMap
            (\i colName ->
                if List.member colName hidden then
                    Nothing

                else
                    let
                        colType =
                            List.drop i colTypes |> List.head |> Maybe.withDefault "VARCHAR"

                        w =
                            estimateWidth colName colType
                    in
                    Just
                        (Grid.stringColumnConfig
                            { id = colName
                            , getter = \row -> Dict.get colName row.values |> Maybe.withDefault ""
                            , localize = identity
                            , title = colName
                            , tooltip = colType
                            , width = w
                            }
                        )
            )
        |> List.filterMap identity


estimateWidth : String -> String -> Int
estimateWidth colName colType =
    let
        nameLen =
            String.length colName

        base =
            nameLen * 9 + 40
    in
    if String.contains "TIMESTAMP" colType then
        max 180 base

    else
        max 90 base
```

A few patterns worth highlighting:

- **No components, just functions.** In Svelte you'd create `<Sidebar>`, `<Toolbar>`, `<Badge>` components. In Elm, `viewSidebar`, `viewToolbar`, `viewBadge` are just functions. No lifecycle hooks, no `$props`, no slot forwarding. A "component" is a function that takes data and returns `Element Msg`.

- **Palette threading.** Every view function takes `Palette` as its first argument (`p`). In Svelte, you'd use a store or CSS variables. In Elm, you pass it explicitly — no hidden global state.

- **`Element.html` bridge.** The grid library (`elm-advanced-grid`) renders standard `Html`. We wrap it with `Element.html` to embed it in our elm-ui layout. This is like Svelte's `{@html}` but type-safe — you can't accidentally inject a string.

- **Conditional attributes.** Look at `viewTableItem` — instead of Svelte's `class:active={isActive}`, we destructure a tuple of attributes based on the condition. Same result, but the compiler checks every attribute exists.

## 6. Building and tooling

The Elm toolchain is minimal compared to a Svelte + Vite setup. No `vite.config.js`, no `postcss.config.js`, no `package.json` scripts. Just `elm make` and `elm-format`.

```bash
cat elm/elm.json
```

```output
{
    "type": "application",
    "source-directories": [
        "src"
    ],
    "elm-version": "0.19.1",
    "dependencies": {
        "direct": {
            "Orange-OpenSource/elm-advanced-grid": "1.0.1",
            "elm/browser": "1.0.2",
            "elm/core": "1.0.5",
            "elm/html": "1.0.1",
            "elm/http": "2.0.0",
            "elm/json": "1.1.4",
            "mdgriffith/elm-ui": "1.1.8"
        },
        "indirect": {
            "FabienHenon/elm-infinite-list-view": "3.3.0",
            "elm/bytes": "1.0.8",
            "elm/file": "1.0.5",
            "elm/parser": "1.1.0",
            "elm/time": "1.0.0",
            "elm/url": "1.0.0",
            "elm/virtual-dom": "1.0.5",
            "elm-community/list-extra": "8.7.0",
            "mpizenberg/elm-pointer-events": "4.0.2",
            "rtfeldman/elm-css": "16.1.1",
            "rtfeldman/elm-hex": "1.0.0"
        }
    },
    "test-dependencies": {
        "direct": {},
        "indirect": {}
    }
}
```

The build is a poe task that formats, compiles, and copies the output:

```bash
rg 'elm-build' -A5 ../../pyproject.toml
```

```output
[tool.poe.tasks.elm-build]
help = "Build the Elm viewer frontend (format + compile)"
sequence = [
    { cmd = "elm-format --yes src/", cwd = "cass/viewer/elm" },
    { cmd = "elm make src/Main.elm --optimize --output=elm.js", cwd = "cass/viewer/elm" },
    { cmd = "cp cass/viewer/elm/elm.js cass/viewer/elm.js" },
```

And elm-format validation runs as part of the lint task (like how Tailwind's Prettier plugin runs on save):

```bash
elm-format --validate elm/src/
```

```output
[]
```

Building compiles all 5 modules into a single JS file:

```bash
cd elm && elm make src/Main.elm --optimize --output=elm.js 2>&1 && wc -c elm.js | awk '{printf "%d KB compiled output\n", $1/1024}'
```

```output
Compiling ...             Success!

    Main ───> elm.js

600 KB compiled output
```

## 7. The HTML shell

With elm-ui handling all layout and styling, the HTML file is minimal — just a mount point and CSS overrides for the grid library (which renders its own DOM that elm-ui can't control):

```bash
wc -l index.html && echo '---' && head -10 index.html && echo '...' && tail -8 index.html
```

```output
      93 index.html
---
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>cass — Database Viewer</title>
  <style>
    /* Reset — elm-ui handles all layout, but we need a clean base */
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { height: 100vh; overflow: hidden; }
...
<body>
  <div id="elm-app"></div>
  <script src="/elm.js"></script>
  <script>
    Elm.Main.init({ node: document.getElementById("elm-app") });
  </script>
</body>
</html>
```

Compare this to a typical Svelte + Tailwind setup where `app.html` has a `%sveltekit.head%` placeholder and Vite injects bundled CSS/JS. Here, Elm's entire runtime and app are in one `elm.js` file — no bundler, no code splitting, no hydration. Just mount and go.

## 8. Data flow summary

Here's how a table selection flows through the app:

    User clicks "students" in sidebar
      → Elm runtime calls `update (SelectTable "students") model`
      → update returns new model + `fetchSchemaAndData "students"` Cmd
      → Elm runtime executes the HTTP requests
      → Responses arrive as `GotSchemaAndData "students" (Ok (schema, data))`
      → update parses rows, initializes grid, returns new model + Cmd.none
      → Elm runtime calls `view newModel`
      → View.elm renders sidebar + toolbar + grid with elm-ui
      → Virtual DOM diffing updates the real DOM

In Svelte, this would be: click handler sets `selectedTable`, a `$effect` fires the fetch, `await` resolves, reactive assignment updates the template. Same flow, different mechanics. The Elm version is more explicit but also more traceable — every step is a named `Msg` you can log.

## Running the viewer

    # From the project root:
    cass view              # Elm frontend (default)
    cass view --classic    # Old AG Grid frontend

    # Development:
    uv run poe elm-build   # format + compile + copy
    uv run poe lint        # includes elm-format --validate
