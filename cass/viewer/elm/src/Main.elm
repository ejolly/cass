port module Main exposing (main)

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
import Browser.Dom
import Dict exposing (Dict)
import Grid
import Json.Decode as D
import Process
import Task
import Types exposing (..)
import View


{-| Port for triggering a CSV file download in JavaScript.

In Svelte/JS you'd create a Blob and an anchor element. In Elm, side
effects that touch browser APIs outside the virtual DOM go through
ports — typed channels between Elm and JS.

-}
port downloadCsv : { filename : String, content : String } -> Cmd msg


{-| Incoming port: JS reports a cell double-click.

JS inspects the DOM to find the column ID and an object mapping column names
to cell values for the clicked row. Elm matches the row by PK values.

Port-compatible: uses a plain JS object (decoded as Json.Decode.Value).

-}
port cellClicked : (D.Value -> msg) -> Sub msg


main : Program () Model Msg
main =
    Browser.element
        { init = init
        , view = View.view
        , update = update
        , subscriptions = subscriptions
        }


subscriptions : Model -> Sub Msg
subscriptions _ =
    cellClicked CellClickedRaw


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
      , pendingCount = 0
      , statusMessage = Nothing
      , columnNames = []
      , columnTypes = []
      , filteredRowCount = 0
      , editing = Nothing
      , showModal = False
      , modalLoading = False
      , modalPushing = False
      , previewData = Nothing
      , pushResults = Nothing
      }
    , Cmd.batch [ Api.fetchTables, Api.fetchPending ]
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
                            pickFirstTable tables
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
                    , editing = Nothing
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
                            View.initGrid tableData.columns tableData.types name schema.primaryKeys rows
                    in
                    ( { model
                        | selectedTable = Just name
                        , schema = Just schema
                        , rows = rows
                        , gridModel = Just gridModel
                        , error = Nothing
                        , columnNames = tableData.columns
                        , columnTypes = tableData.types
                        , filteredRowCount = List.length rows
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
            let
                filtered =
                    if String.isEmpty newText then
                        model.rows

                    else
                        List.filter (Api.matchesSearch newText) model.rows

                primaryKeys =
                    model.schema
                        |> Maybe.map .primaryKeys
                        |> Maybe.withDefault []

                newGridModel =
                    case model.selectedTable of
                        Just tableName ->
                            Just (View.initGrid model.columnNames model.columnTypes tableName primaryKeys filtered)

                        Nothing ->
                            model.gridModel
            in
            ( { model
                | searchText = newText
                , gridModel = newGridModel
                , filteredRowCount = List.length filtered
              }
            , Cmd.none
            )

        ToggleSidebar ->
            ( { model | sidebarCollapsed = not model.sidebarCollapsed }, Cmd.none )

        GotPending result ->
            case result of
                Ok count ->
                    ( { model | pendingCount = count }, Cmd.none )

                Err _ ->
                    -- Canvas may not be configured — ignore
                    ( model, Cmd.none )

        ClearStatus expectedText ->
            case model.statusMessage of
                Just status ->
                    if status.text == expectedText then
                        ( { model | statusMessage = Nothing }, Cmd.none )

                    else
                        ( model, Cmd.none )

                Nothing ->
                    ( model, Cmd.none )

        ExportCsv ->
            case model.selectedTable of
                Just tableName ->
                    let
                        displayedCols =
                            View.getDisplayedColumns tableName model.columnNames

                        filtered =
                            if String.isEmpty model.searchText then
                                model.rows

                            else
                                List.filter (Api.matchesSearch model.searchText) model.rows

                        csv =
                            Api.buildCsvContent displayedCols filtered
                    in
                    ( model, downloadCsv { filename = tableName ++ ".csv", content = csv } )

                Nothing ->
                    ( model, Cmd.none )

        FocusSearch ->
            ( model
            , Browser.Dom.focus "search-box"
                |> Task.attempt (\_ -> NoOp)
            )

        -- Cell editing: decode port data and check editability
        CellClickedRaw raw ->
            case D.decodeValue cellClickDecoder raw of
                Ok { columnId, rowValues } ->
                    case ( model.schema, model.selectedTable ) of
                        ( Just schema, Just tableName ) ->
                            let
                                realCols =
                                    List.map .name schema.columns

                                effectiveEditable =
                                    schema.editable && not (View.isCombinedTable tableName)

                                isEditable =
                                    effectiveEditable
                                        && not (List.member columnId schema.primaryKeys)
                                        && List.member columnId realCols
                            in
                            if isEditable then
                                let
                                    pk =
                                        Dict.filter (\k _ -> List.member k schema.primaryKeys) rowValues

                                    value =
                                        Dict.get columnId rowValues |> Maybe.withDefault ""
                                in
                                update (StartEdit columnId value pk) model

                            else
                                ( model, Cmd.none )

                        _ ->
                            ( model, Cmd.none )

                Err _ ->
                    ( model, Cmd.none )

        StartEdit column value pk ->
            ( { model
                | editing =
                    Just
                        { column = column
                        , value = value
                        , originalValue = value
                        , pk = pk
                        }
              }
            , Browser.Dom.focus "cell-editor"
                |> Task.attempt (\_ -> NoOp)
            )

        EditChanged newValue ->
            case model.editing of
                Just ed ->
                    ( { model | editing = Just { ed | value = newValue } }, Cmd.none )

                Nothing ->
                    ( model, Cmd.none )

        CommitEdit ->
            case ( model.editing, model.selectedTable ) of
                ( Just ed, Just table ) ->
                    if ed.value == ed.originalValue then
                        ( { model | editing = Nothing }, Cmd.none )

                    else
                        ( { model | editing = Nothing }
                        , Api.updateCell table ed.pk ed.column ed.value
                        )

                _ ->
                    ( { model | editing = Nothing }, Cmd.none )

        CancelEdit ->
            ( { model | editing = Nothing }, Cmd.none )

        GotUpdateResult table pk column result ->
            case result of
                Ok resp ->
                    if resp.ok then
                        let
                            newPending =
                                resp.pendingCount |> Maybe.withDefault model.pendingCount
                        in
                        ( { model
                            | pendingCount = newPending
                            , statusMessage = Just { text = "Saved", statusClass = "success" }
                          }
                        , Cmd.batch
                            [ setStatusTimer "Saved" 3000
                            , Api.fetchSchemaAndData table
                            ]
                        )

                    else
                        ( { model
                            | statusMessage =
                                Just
                                    { text = resp.error |> Maybe.withDefault "Update failed"
                                    , statusClass = "error"
                                    }
                          }
                        , setStatusTimer (resp.error |> Maybe.withDefault "Update failed") 3000
                        )

                Err _ ->
                    ( { model
                        | statusMessage = Just { text = "Network error", statusClass = "error" }
                      }
                    , setStatusTimer "Network error" 3000
                    )

        -- Canvas push modal
        OpenPushModal ->
            ( { model
                | showModal = True
                , modalLoading = True
                , modalPushing = False
                , previewData = Nothing
                , pushResults = Nothing
              }
            , Api.fetchPreview
            )

        ClosePushModal ->
            ( { model
                | showModal = False
                , modalLoading = False
                , modalPushing = False
                , previewData = Nothing
                , pushResults = Nothing
              }
            , Cmd.none
            )

        GotPreview result ->
            case result of
                Ok preview ->
                    ( { model | modalLoading = False, previewData = Just preview }, Cmd.none )

                Err err ->
                    ( { model
                        | modalLoading = False
                        , previewData = Nothing
                        , error = Just (Api.httpErrorToString err)
                      }
                    , Cmd.none
                    )

        ApplyPush ->
            ( { model | modalPushing = True }, Api.applyPush )

        GotApplyResult result ->
            case result of
                Ok resp ->
                    if resp.ok then
                        ( { model
                            | showModal = False
                            , modalPushing = False
                            , pendingCount = 0
                            , statusMessage = Just { text = "Pushed to Canvas", statusClass = "success" }
                            , pushResults = Nothing
                            , previewData = Nothing
                          }
                        , Cmd.batch
                            [ setStatusTimer "Pushed to Canvas" 6000
                            , case model.selectedTable of
                                Just t ->
                                    Api.fetchSchemaAndData t

                                Nothing ->
                                    Cmd.none
                            ]
                        )

                    else
                        ( { model
                            | modalPushing = False
                            , pushResults = Just resp.results
                          }
                        , Api.fetchPending
                        )

                Err _ ->
                    ( { model
                        | modalPushing = False
                        , statusMessage = Just { text = "Push failed", statusClass = "error" }
                        , showModal = False
                      }
                    , setStatusTimer "Push failed" 6000
                    )

        EscapePressed ->
            if model.showModal then
                update ClosePushModal model

            else if model.editing /= Nothing then
                update CancelEdit model

            else
                ( model, Cmd.none )

        NoOp ->
            ( model, Cmd.none )


{-| Decode the cellClicked port payload: { columnId, rowValues }.
-}
cellClickDecoder : D.Decoder { columnId : String, rowValues : Dict String String }
cellClickDecoder =
    D.map2 (\c r -> { columnId = c, rowValues = r })
        (D.field "columnId" D.string)
        (D.field "rowValues" (D.dict D.string))


{-| Schedule a ClearStatus message after a delay.
-}
setStatusTimer : String -> Float -> Cmd Msg
setStatusTimer text delay =
    Process.sleep delay
        |> Task.perform (\_ -> ClearStatus text)


{-| Pick the first table to auto-select, preferring combined tables.

Matches the sidebar display order: Combined Data → Canvas → GitHub.

-}
pickFirstTable : List TableInfo -> Maybe String
pickFirstTable tables =
    let
        combined =
            List.filter
                (\t ->
                    not (String.startsWith "canvas_" t.name)
                        && not (String.startsWith "gh_" t.name)
                )
                tables

        canvas =
            List.filter (\t -> String.startsWith "canvas_" t.name) tables

        github =
            List.filter (\t -> String.startsWith "gh_" t.name) tables
    in
    List.concatMap identity [ combined, canvas, github ]
        |> List.head
        |> Maybe.map .name
