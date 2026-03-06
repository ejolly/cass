module View exposing (getDisplayedColumns, initGrid, view)

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
import Html.Attributes
import Html.Events
import Json.Decode as D
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
        , htmlAttribute (Html.Events.preventDefaultOn "keydown" keyDecoder)
        ]
        (row [ width fill, height fill ]
            [ viewSidebar p model
            , viewMain p model
            ]
        )


{-| Keyboard shortcut decoder.

Ctrl+K / Cmd+K focuses the search box (with preventDefault to block
the browser's default Ctrl+K behavior). Same as the classic viewer's
`document.addEventListener("keydown", ...)`.

-}
keyDecoder : D.Decoder ( Msg, Bool )
keyDecoder =
    D.map3
        (\key ctrl meta ->
            if (ctrl || meta) && key == "k" then
                ( FocusSearch, True )

            else
                ( NoOp, False )
        )
        (D.field "key" D.string)
        (D.field "ctrlKey" D.bool)
        (D.field "metaKey" D.bool)



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

        -- alignRight on this row pushes it to the far right.
        -- Equivalent to Tailwind's `ml-auto` on a flex child.
        , row [ alignRight, spacing 8 ]
            [ viewSearchBox p model
            , viewExportButton p model
            , viewPushButton p model
            , viewStatusMessage p model
            ]
        ]


viewBadge : Palette -> Model -> Element Msg
viewBadge p model =
    case ( model.schema, model.selectedTable ) of
        ( Just schema, Just tableName ) ->
            let
                effectiveEditable =
                    schema.editable && not (isCombinedTable tableName)

                ( label, bgColor, textColor ) =
                    if effectiveEditable then
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

        _ ->
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
        , htmlAttribute (Html.Attributes.id "search-box")
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


viewExportButton : Palette -> Model -> Element Msg
viewExportButton p model =
    case model.selectedTable of
        Just _ ->
            Input.button
                [ Font.size 12
                , paddingXY 10 5
                , Border.width 1
                , Border.color p.inputBorder
                , Border.rounded 6
                , Background.color p.inputBg
                , Font.color p.text
                , mouseOver
                    [ Border.color p.accent
                    , Background.color p.accentLight
                    ]
                ]
                { onPress = Just ExportCsv
                , label = text "Export CSV"
                }

        Nothing ->
            none


viewPushButton : Palette -> Model -> Element Msg
viewPushButton p model =
    if model.pendingCount > 0 then
        -- Non-interactive indicator showing pending Canvas changes.
        -- Phase 2 will add the preview modal and push flow.
        el
            [ Font.size 12
            , Font.semiBold
            , paddingXY 10 5
            , Border.width 1
            , Border.color p.accent
            , Border.rounded 6
            , Background.color p.accentLight
            , Font.color p.accent
            ]
            (row [ spacing 5 ]
                [ text "Push to Canvas"
                , el
                    [ Font.size 10
                    , Font.semiBold
                    , Font.color p.white
                    , Font.center
                    , Background.color p.accent
                    , Border.rounded 9
                    , paddingXY 4 0
                    , width (minimum 18 shrink)
                    , height (px 18)
                    ]
                    (text (String.fromInt model.pendingCount))
                ]
            )

    else
        none


viewStatusMessage : Palette -> Model -> Element Msg
viewStatusMessage p model =
    case model.statusMessage of
        Just status ->
            let
                fontColor =
                    case status.statusClass of
                        "success" ->
                            p.success

                        "error" ->
                            p.error

                        _ ->
                            p.text
            in
            el [ Font.size 12, Font.color fontColor ]
                (text status.text)

        Nothing ->
            none



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
                    column [ centerX, centerY, spacing 8 ]
                        [ el [ centerX, Font.color p.textDim, Font.size 14 ]
                            (text "Select a table from the sidebar")
                        , el [ centerX, Font.size 12, Font.color p.textFaint ]
                            (text "Use ⌘K to search within a table")
                        ]


rowCountText : Model -> String
rowCountText model =
    let
        total =
            List.length model.rows

        colCount =
            List.length model.columnNames

        filterText =
            if String.isEmpty model.searchText then
                ""

            else
                " (" ++ String.fromInt model.filteredRowCount ++ " matching)"
    in
    if total > 0 then
        String.fromInt total ++ " rows · " ++ String.fromInt colCount ++ " columns" ++ filterText

    else
        ""



-- HELPERS


isCombinedTable : String -> Bool
isCombinedTable name =
    not (String.startsWith "canvas_" name)
        && not (String.startsWith "gh_" name)



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


{-| Preferred column order for specific tables.

Matches the `COLUMN_OVERRIDES.order` from the classic viewer — puts
the most useful columns first and appends any remaining columns after.

-}
columnOrdering : Dict String (List String)
columnOrdering =
    Dict.fromList
        [ ( "canvas_assignments"
          , [ "assignment_group", "name", "points_possible", "due_at", "published" ]
          )
        , ( "canvas_submissions"
          , [ "student_name", "assignment_name", "assignment_group", "submitted", "submitted_at", "late", "score", "workflow_state" ]
          )
        , ( "canvas_grades"
          , [ "student_name", "assignment_name", "assignment_group", "score", "posted_grade", "updated_at" ]
          )
        ]


{-| Get the visible columns in display order for a table.

Applies hidden-column filtering and custom ordering. Used both for
grid display and CSV export.

-}
getDisplayedColumns : String -> List String -> List String
getDisplayedColumns tableName allCols =
    let
        hidden =
            Dict.get tableName hiddenColumns |> Maybe.withDefault []

        visible =
            List.filter (\c -> not (List.member c hidden)) allCols
    in
    case Dict.get tableName columnOrdering of
        Nothing ->
            visible

        Just ordered ->
            let
                orderedVisible =
                    List.filter (\c -> List.member c visible) ordered

                remaining =
                    List.filter (\c -> not (List.member c ordered)) visible
            in
            orderedVisible ++ remaining


{-| Build grid config and initialize the grid model.

Separated from the view so Main.update can call it when data arrives.
The grid library needs its dimensions at init time (like AG Grid's
`domLayout` or `containerStyle` props in the JS world).

-}
initGrid : List String -> List String -> String -> List String -> List Row -> Grid.Model Row
initGrid colNames colTypes tableName primaryKeys rows =
    let
        columns =
            buildGridColumns colNames colTypes tableName primaryKeys

        gridConfig : Grid.Config Row
        gridConfig =
            { canSelectRows = False
            , columns = columns
            , containerHeight = 800
            , containerWidth = 1200
            , hasFilters = True
            , headerHeight = 60
            , lineHeight = 32
            , rowClass =
                \item ->
                    if tableName == "canvas_assignments" then
                        case Dict.get "published" item.data.values of
                            Just "No" ->
                                "unpublished-row"

                            _ ->
                                ""

                    else
                        ""
            }
    in
    Grid.init gridConfig rows


buildGridColumns : List String -> List String -> String -> List String -> List (ColumnConfig Row)
buildGridColumns colNames colTypes tableName primaryKeys =
    let
        displayedCols =
            getDisplayedColumns tableName colNames

        colTypeMap =
            List.map2 Tuple.pair colNames colTypes
                |> Dict.fromList
    in
    List.map
        (\colName ->
            let
                colType =
                    Dict.get colName colTypeMap |> Maybe.withDefault "VARCHAR"

                isPK =
                    List.member colName primaryKeys

                title =
                    if isPK then
                        colName ++ " (PK)"

                    else
                        colName

                w =
                    estimateWidth colName colType
            in
            Grid.stringColumnConfig
                { id = colName
                , getter = \row -> Dict.get colName row.values |> Maybe.withDefault ""
                , localize = identity
                , title = title
                , tooltip = colType
                , width = w
                }
        )
        displayedCols


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
