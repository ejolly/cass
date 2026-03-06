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
