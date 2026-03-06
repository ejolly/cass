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
