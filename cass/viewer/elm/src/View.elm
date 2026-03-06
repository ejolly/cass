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
            Theme.paletteFor model.darkMode
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
        , Font.size Theme.textBase
        , Font.color p.text
        , Background.color p.bg
        , htmlAttribute (Html.Events.preventDefaultOn "keydown" keyDecoder)
        , case model.modal of
            ModalClosed ->
                inFront none

            _ ->
                inFront (viewModal p model)
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

            else if key == "Escape" then
                ( EscapePressed, True )

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
            , column [ width fill, paddingXY 0 Theme.sp1 ]
                (viewTableGroups p model)
            ]


viewSidebarHeader : Palette -> Element Msg
viewSidebarHeader p =
    row
        [ width fill
        , paddingXY Theme.sp4 Theme.sp3
        , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
        , Border.color p.border
        ]
        [ el
            [ Font.size Theme.textSm
            , Font.bold
            , Font.color p.textDim
            , Font.letterSpacing 0.8
            ]
            (text "CASS")

        -- alignRight pushes this button to the right edge.
        -- In Tailwind: `ml-auto`. In Svelte: `style="margin-left: auto"`.
        , Input.button
            [ alignRight
            , Font.size Theme.textLg
            , Font.color p.textDim
            , padding Theme.sp1
            , Border.rounded Theme.rounded
            , mouseOver [ Background.color p.sidebarActive ]
            ]
            { onPress = Just ToggleSidebar
            , label = text "‹"
            }
        ]


viewTableGroups : Palette -> Model -> List (Element Msg)
viewTableGroups p model =
    let
        combined =
            List.filter (\t -> classifyTable t.name == Combined) model.tables

        canvas =
            List.filter (\t -> classifyTable t.name == Canvas) model.tables

        github =
            List.filter (\t -> classifyTable t.name == GitHub) model.tables

        viewGroup label items =
            if List.isEmpty items then
                []

            else
                [ column [ width fill, paddingEach { top = 0, right = 0, bottom = Theme.sp1, left = 0 } ]
                    (el
                        [ Font.size Theme.textXxs
                        , Font.semiBold
                        , Font.color p.textDim
                        , Font.letterSpacing 0.6
                        , paddingEach { top = Theme.sp3, right = Theme.sp4, bottom = Theme.sp1, left = Theme.sp4 }
                        ]
                        (text (String.toUpper label))
                        :: List.map (viewTableItem p model.selectedTable) items
                    )
                ]
    in
    viewGroup "Combined Data" combined
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
         , paddingXY Theme.sp4 Theme.sp2
         , Font.family Theme.mono
         , Font.size Theme.textBase
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
        , moveDown (toFloat Theme.sp25)
        , moveRight (toFloat Theme.sp2)
        , padding Theme.sp1
        , Font.size Theme.textLg
        , Font.color p.textDim
        , Background.color p.sidebarBg
        , Border.width 1
        , Border.color p.border
        , Border.rounded Theme.rounded
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
        , paddingXY Theme.sp4 Theme.sp2
        , spacing Theme.sp25
        , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
        , Border.color p.border
        , height (px Theme.toolbarHeight)
        ]
        [ el [ Font.semiBold, Font.size Theme.textSm ]
            (text (Maybe.withDefault "" model.selectedTable))
        , viewBadge p model
        , el [ Font.size Theme.textXs, Font.color p.textDim ]
            (text (rowCountText model))

        -- alignRight on this row pushes it to the far right.
        -- Equivalent to Tailwind's `ml-auto` on a flex child.
        , row [ alignRight, spacing Theme.sp2 ]
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
                    schema.editable && classifyTable tableName /= Combined

                ( label, bgColor, textColor ) =
                    if effectiveEditable then
                        ( "EDITABLE", p.editableBg, p.editableText )

                    else
                        ( "READ-ONLY", p.badgeBg, p.badgeText )
            in
            el
                [ Font.size Theme.textXxs
                , Font.semiBold
                , Font.letterSpacing 0.3
                , Font.color textColor
                , Background.color bgColor
                , paddingXY Theme.sp2 Theme.sp05
                , Border.rounded Theme.rounded
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
        [ width (px Theme.searchBoxWidth)
        , Font.size Theme.textBase
        , paddingXY Theme.sp25 Theme.sp15
        , Border.width 1
        , Border.color p.inputBorder
        , Border.rounded Theme.roundedMd
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
                [ Font.size Theme.textXs
                , paddingXY Theme.sp25 Theme.sp15
                , Border.width 1
                , Border.color p.inputBorder
                , Border.rounded Theme.roundedMd
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
        Input.button
            [ Font.size Theme.textXs
            , Font.semiBold
            , paddingXY Theme.sp25 Theme.sp15
            , Border.width 1
            , Border.color p.accent
            , Border.rounded Theme.roundedMd
            , Background.color p.accentLight
            , Font.color p.accent
            , mouseOver
                [ Background.color p.accent
                , Font.color p.white
                ]
            ]
            { onPress = Just OpenPushModal
            , label =
                row [ spacing Theme.sp1 ]
                    [ text "Push to Canvas"
                    , el
                        [ Font.size Theme.textXxs
                        , Font.semiBold
                        , Font.color p.white
                        , Font.center
                        , Background.color p.accent
                        , Border.rounded Theme.roundedFull
                        , paddingXY Theme.sp1 0
                        , width (minimum 18 shrink)
                        , height (px 18)
                        ]
                        (text (String.fromInt model.pendingCount))
                    ]
            }

    else
        none


viewStatusMessage : Palette -> Model -> Element Msg
viewStatusMessage p model =
    case model.statusMessage of
        Just status ->
            let
                -- Pattern matching on a custom type instead of string comparison.
                -- The compiler will tell us if we add a new StatusLevel variant
                -- but forget to handle it here.
                fontColor =
                    case status.level of
                        Success ->
                            p.success

                        Error ->
                            p.error
            in
            el [ Font.size Theme.textXs, Font.color fontColor ]
                (text status.text)

        Nothing ->
            none



-- GRID AREA


viewGridArea : Palette -> Model -> Element Msg
viewGridArea p model =
    case model.gridModel of
        Just gm ->
            el [ width fill, height fill, clip ]
                (column [ width fill, height fill ]
                    [ case model.editing of
                        Just ed ->
                            viewEditBar p ed

                        Nothing ->
                            none
                    , el [ width fill, height fill ]
                        (Grid.view gm
                            |> Html.map GridMsg
                            |> html
                        )
                    ]
                )

        Nothing ->
            case model.error of
                Just err ->
                    el [ centerX, centerY, Font.color p.error ]
                        (text err)

                Nothing ->
                    column [ centerX, centerY, spacing Theme.sp2 ]
                        [ el [ centerX, Font.color p.textDim, Font.size Theme.textSm ]
                            (text "Select a table from the sidebar")
                        , el [ centerX, Font.size Theme.textXs, Font.color p.textFaint ]
                            (text "Use ⌘K to search within a table")
                        ]


{-| Inline edit bar shown above the grid when editing a cell.
-}
viewEditBar : Palette -> EditState -> Element Msg
viewEditBar p ed =
    row
        [ width fill
        , paddingXY Theme.sp4 Theme.sp2
        , spacing Theme.sp25
        , Background.color p.accentLight
        , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
        , Border.color p.accent
        ]
        [ el [ Font.size Theme.textXs, Font.semiBold, Font.color p.accent ]
            (text ("Editing: " ++ ed.column))
        , Input.text
            [ width (px Theme.editInputWidth)
            , Font.size Theme.textBase
            , paddingXY Theme.sp25 Theme.sp15
            , Border.width 1
            , Border.color p.accent
            , Border.rounded Theme.rounded
            , Background.color p.inputBg
            , Font.color p.text
            , htmlAttribute (Html.Attributes.id "cell-editor")
            , htmlAttribute
                (Html.Events.on "keydown"
                    (D.field "key" D.string
                        |> D.andThen
                            (\key ->
                                case key of
                                    "Enter" ->
                                        D.succeed CommitEdit

                                    "Escape" ->
                                        D.succeed CancelEdit

                                    _ ->
                                        D.fail "ignore"
                            )
                    )
                )
            ]
            { onChange = EditChanged
            , text = ed.value
            , placeholder = Nothing
            , label = Input.labelHidden "Edit cell value"
            }
        , Input.button
            [ Font.size Theme.textXs
            , paddingXY Theme.sp25 Theme.sp15
            , Border.rounded Theme.rounded
            , Background.color p.accent
            , Font.color p.white
            , mouseOver [ alpha 0.9 ]
            ]
            { onPress = Just CommitEdit
            , label = text "Save"
            }
        , Input.button
            [ Font.size Theme.textXs
            , paddingXY Theme.sp25 Theme.sp15
            , Border.rounded Theme.rounded
            , Border.width 1
            , Border.color p.inputBorder
            , Background.color p.inputBg
            , Font.color p.text
            , mouseOver [ Border.color p.accent ]
            ]
            { onPress = Just CancelEdit
            , label = text "Cancel"
            }
        ]



-- MODAL


{-| Full-screen overlay with the Canvas push preview/apply modal.
-}
viewModal : Palette -> Model -> Element Msg
viewModal p model =
    -- Overlay background (click to close)
    el
        [ width fill
        , height fill
        , Background.color (rgba 0 0 0 0.5)
        , htmlAttribute (Html.Events.onClick ClosePushModal)
        ]
        -- Modal card (stop propagation so clicks inside don't close)
        (el
            [ centerX
            , centerY
            , width (px Theme.modalWidth)
            , height (maximum Theme.modalMaxHeight shrink)
            , Background.color p.bg
            , Border.rounded Theme.roundedXl
            , Border.width 1
            , Border.color p.border
            , Border.shadow
                { offset = ( 0, Theme.sp5 |> toFloat )
                , size = 0
                , blur = 60
                , color = rgba 0 0 0 0.3
                }
            , htmlAttribute (Html.Events.stopPropagationOn "click" (D.succeed ( NoOp, True )))
            ]
            (column [ width fill, height fill ]
                [ viewModalHeader p
                , viewModalBody p model
                , viewModalFooter p model
                ]
            )
        )


viewModalHeader : Palette -> Element Msg
viewModalHeader p =
    row
        [ width fill
        , paddingXY Theme.sp5 Theme.sp4
        , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
        , Border.color p.border
        ]
        [ el [ Font.semiBold, Font.size Theme.textSm ] (text "Push to Canvas")
        , Input.button
            [ alignRight
            , padding Theme.sp1
            , Font.size Theme.textLg
            , Font.color p.textDim
            , Border.rounded Theme.rounded
            , mouseOver [ Background.color p.sidebarActive ]
            ]
            { onPress = Just ClosePushModal
            , label = text "×"
            }
        ]


{-| Modal body — pattern matches on `ModalState` instead of juggling
multiple booleans. Each variant renders exactly the UI for that state.
-}
viewModalBody : Palette -> Model -> Element Msg
viewModalBody p model =
    el
        [ width fill
        , paddingXY Theme.sp5 Theme.sp4
        , scrollbarY
        , height (fill |> minimum 100)
        ]
        (case model.modal of
            ModalLoading ->
                el [ centerX, Font.color p.textDim ] (text "Comparing with Canvas...")

            ModalResults results ->
                viewPushResults p results

            ModalPreview preview ->
                viewPreviewChanges p preview

            ModalPushing preview ->
                viewPreviewChanges p preview

            ModalError err ->
                el [ Font.color p.error ] (text err)

            ModalClosed ->
                none
        )


viewPreviewChanges : Palette -> PreviewData -> Element Msg
viewPreviewChanges p preview =
    if List.isEmpty preview.changes then
        el [ centerX, Font.color p.textDim ] (text "No pending changes")

    else
        let
            assignmentChanges =
                List.filter (\c -> c.table == "canvas_assignments") preview.changes

            gradeChanges =
                List.filter (\c -> c.table == "canvas_grades") preview.changes
        in
        column [ width fill, spacing Theme.sp4 ]
            [ if List.isEmpty assignmentChanges then
                none

              else
                viewChangeTable p "Assignment changes" [ "Assignment", "Field", "On Canvas", "New value" ] assignmentChanges viewAssignmentRow
            , if List.isEmpty gradeChanges then
                none

              else
                viewChangeTable p "Grade changes" [ "Student — Assignment", "On Canvas", "New grade" ] gradeChanges viewGradeRow
            , if preview.hasConflicts then
                el
                    [ width fill
                    , padding Theme.sp3
                    , Background.color (rgba 220 38 38 0.08)
                    , Border.width 1
                    , Border.color (rgba 220 38 38 0.25)
                    , Border.rounded Theme.roundedMd
                    , Font.size Theme.textXs
                    , Font.color p.error
                    ]
                    (text "Some Canvas values differ from when you last pulled. Pushing will overwrite the current Canvas values.")

              else
                none
            ]


{-| Render a table of changes with a header row and data rows.

Uses a plain `column` with a manual header `row` — simpler than
`Element.table` and keeps the headers aligned with data rows since
both use `width fill` on each cell.

-}
viewChangeTable : Palette -> String -> List String -> List CanvasChange -> (Palette -> CanvasChange -> Element Msg) -> Element Msg
viewChangeTable p title headers changes rowView =
    column [ width fill, spacing Theme.sp15 ]
        [ el [ Font.semiBold, Font.size Theme.textBase ] (text title)
        , column [ width fill ]
            (row
                [ width fill
                , Border.widthEach { bottom = 2, left = 0, right = 0, top = 0 }
                , Border.color p.border
                ]
                (List.map
                    (\h ->
                        el
                            [ width fill
                            , paddingXY Theme.sp25 Theme.sp15
                            , Font.size Theme.textXxs
                            , Font.color p.textDim
                            , Font.semiBold
                            ]
                            (text (String.toUpper h))
                    )
                    headers
                )
                :: List.map (rowView p) changes
            )
        ]


viewAssignmentRow : Palette -> CanvasChange -> Element Msg
viewAssignmentRow p ch =
    case ch.error of
        Just err ->
            row [ width fill, paddingXY Theme.sp25 Theme.sp15, Font.size Theme.textBase, Font.color p.error ]
                [ text (ch.name ++ ": " ++ err) ]

        Nothing ->
            row
                [ width fill
                , paddingXY Theme.sp25 Theme.sp15
                , Font.size Theme.textBase
                , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
                , Border.color p.border
                , if ch.conflict then
                    Background.color (rgba 220 38 38 0.08)

                  else
                    Background.color (rgba 0 0 0 0)
                ]
                [ el [ width fill ] (text ch.name)
                , el [ width fill ]
                    (row [ spacing Theme.sp1 ]
                        [ text ch.column
                        , if ch.conflict then
                            el [ Font.color p.error ] (text "⚠")

                          else
                            none
                        ]
                    )
                , el [ width fill, Font.color p.textDim ] (text (Maybe.withDefault "null" ch.live))
                , el [ width fill, Font.semiBold ] (text (Maybe.withDefault "null" ch.current))
                ]


viewGradeRow : Palette -> CanvasChange -> Element Msg
viewGradeRow p ch =
    case ch.error of
        Just err ->
            row [ width fill, paddingXY Theme.sp25 Theme.sp15, Font.size Theme.textBase, Font.color p.error ]
                [ text (ch.name ++ ": " ++ err) ]

        Nothing ->
            row
                [ width fill
                , paddingXY Theme.sp25 Theme.sp15
                , Font.size Theme.textBase
                , Border.widthEach { bottom = 1, left = 0, right = 0, top = 0 }
                , Border.color p.border
                , if ch.conflict then
                    Background.color (rgba 220 38 38 0.08)

                  else
                    Background.color (rgba 0 0 0 0)
                ]
                [ el [ width fill ]
                    (row [ spacing Theme.sp1 ]
                        [ text ch.name
                        , if ch.conflict then
                            el [ Font.color p.error ] (text "⚠")

                          else
                            none
                        ]
                    )
                , el [ width fill, Font.color p.textDim ] (text (Maybe.withDefault "null" ch.live))
                , el [ width fill, Font.semiBold ] (text (Maybe.withDefault "null" ch.current))
                ]


viewPushResults : Palette -> List PushResult -> Element Msg
viewPushResults p results =
    let
        succeeded =
            List.filter .ok results

        failed =
            List.filter (\r -> not r.ok) results
    in
    column [ width fill, spacing Theme.sp2 ]
        [ el [ Font.semiBold ]
            (text
                (String.fromInt (List.length succeeded)
                    ++ " pushed, "
                    ++ String.fromInt (List.length failed)
                    ++ " failed:"
                )
            )
        , column [ width fill, spacing Theme.sp1 ]
            (List.map
                (\r ->
                    if r.ok then
                        el [ Font.color p.success, paddingXY 0 Theme.sp05 ]
                            (text ("✓ Assignment " ++ (r.canvasId |> Maybe.map String.fromInt |> Maybe.withDefault "?")))

                    else
                        el [ Font.color p.error, paddingXY 0 Theme.sp05 ]
                            (text
                                ("✗ Assignment "
                                    ++ (r.canvasId |> Maybe.map String.fromInt |> Maybe.withDefault "?")
                                    ++ ": "
                                    ++ Maybe.withDefault "Unknown error" r.error
                                )
                            )
                )
                results
            )
        ]


{-| Modal footer — the button label and available actions change based
on the current `ModalState`. Pattern matching makes each case explicit.
-}
viewModalFooter : Palette -> Model -> Element Msg
viewModalFooter p model =
    row
        [ width fill
        , paddingXY Theme.sp5 Theme.sp3
        , spacing Theme.sp2
        , Border.widthEach { bottom = 0, left = 0, right = 0, top = 1 }
        , Border.color p.border
        , alignBottom
        ]
        [ el [ alignRight ] none
        , row [ alignRight, spacing Theme.sp2 ]
            [ Input.button
                [ Font.size Theme.textXs
                , paddingXY Theme.sp3 Theme.sp15
                , Border.width 1
                , Border.color p.inputBorder
                , Border.rounded Theme.roundedMd
                , Background.color p.inputBg
                , Font.color p.text
                , mouseOver [ Border.color p.accent ]
                ]
                { onPress = Just ClosePushModal
                , label =
                    text
                        (case model.modal of
                            ModalResults _ ->
                                "Close"

                            _ ->
                                "Cancel"
                        )
                }
            , case model.modal of
                ModalPreview preview ->
                    let
                        pushableCount =
                            List.length (List.filter (\c -> c.error == Nothing) preview.changes)
                    in
                    if pushableCount > 0 then
                        Input.button
                            [ Font.size Theme.textXs
                            , Font.semiBold
                            , paddingXY Theme.sp3 Theme.sp15
                            , Border.rounded Theme.roundedMd
                            , Background.color p.accent
                            , Font.color p.white
                            , mouseOver [ alpha 0.9 ]
                            ]
                            { onPress = Just ApplyPush
                            , label = text ("Push " ++ String.fromInt pushableCount ++ " change" ++ pluralize pushableCount)
                            }

                    else
                        none

                ModalPushing _ ->
                    el
                        [ Font.size Theme.textXs
                        , Font.semiBold
                        , paddingXY Theme.sp3 Theme.sp15
                        , Border.rounded Theme.roundedMd
                        , Background.color p.accent
                        , Font.color p.white
                        , alpha 0.5
                        ]
                        (text "Pushing...")

                _ ->
                    none
            ]
        ]


pluralize : Int -> String
pluralize n =
    if n == 1 then
        ""

    else
        "s"


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
initGrid : List String -> List String -> String -> List String -> List Row -> Model -> Grid.Model Row
initGrid colNames colTypes tableName primaryKeys rows model =
    let
        columns =
            buildGridColumns colNames colTypes tableName primaryKeys gridWidth

        -- Subtract sidebar width from viewport
        sidebarW =
            if model.sidebarCollapsed then
                0

            else
                Theme.sidebarWidth

        gridWidth =
            model.windowWidth - sidebarW

        -- containerHeight is the grid BODY height (excludes header).
        -- Available = viewport - toolbar - grid header
        gridHeight =
            model.windowHeight - Theme.toolbarHeight - Theme.gridHeaderHeight

        gridConfig : Grid.Config Row
        gridConfig =
            { canSelectRows = False
            , columns = columns
            , containerHeight = gridHeight
            , containerWidth = gridWidth
            , hasFilters = True
            , headerHeight = Theme.gridHeaderHeight
            , lineHeight = Theme.sp8
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


buildGridColumns : List String -> List String -> String -> List String -> Int -> List (ColumnConfig Row)
buildGridColumns colNames colTypes tableName primaryKeys containerWidth =
    let
        displayedCols =
            getDisplayedColumns tableName colNames

        colTypeMap =
            List.map2 Tuple.pair colNames colTypes
                |> Dict.fromList

        -- Compute base widths first, then scale to fill container
        baseWidths =
            List.map
                (\colName ->
                    let
                        colType =
                            Dict.get colName colTypeMap |> Maybe.withDefault "VARCHAR"
                    in
                    ( colName, estimateWidth colName colType )
                )
                displayedCols

        totalBase =
            List.foldl (\( _, w ) acc -> acc + w) 0 baseWidths

        scale =
            if totalBase > 0 && containerWidth > totalBase then
                toFloat containerWidth / toFloat totalBase

            else
                1.0
    in
    List.map
        (\( colName, baseW ) ->
            let
                isPK =
                    List.member colName primaryKeys

                title =
                    if isPK then
                        colName ++ " (PK)"

                    else
                        colName

                colType =
                    Dict.get colName colTypeMap |> Maybe.withDefault "VARCHAR"

                w =
                    round (toFloat baseW * scale)
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
        baseWidths


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
