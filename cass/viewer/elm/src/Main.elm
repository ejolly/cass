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
import Dict
import Grid
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
      , pendingCount = 0
      , statusMessage = Nothing
      , columnNames = []
      , columnTypes = []
      , filteredRowCount = 0
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

        NoOp ->
            ( model, Cmd.none )


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
