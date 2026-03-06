module Main exposing (main)

{-| cass database viewer — Elm frontend with elm-advanced-grid.

Phase 1: Read-only table display with sidebar navigation,
column sorting, and filtering via elm-advanced-grid.
-}

import Browser
import Dict exposing (Dict)
import Grid exposing (ColumnConfig, Msg(..), Sorting(..), stringColumnConfig)
import Html exposing (Html, button, div, input, nav, span, text)
import Html.Attributes exposing (class, disabled, id, placeholder, style, title, type_, value)
import Html.Events exposing (onClick, onInput)
import Http
import Json.Decode as D
import Task



-- MAIN


main : Program () Model Msg
main =
    Browser.element
        { init = init
        , view = view
        , update = update
        , subscriptions = \_ -> Sub.none
        }



-- MODEL


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
We normalize everything to strings for display in elm-advanced-grid.
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


type Msg
    = GotTables (Result Http.Error (List TableInfo))
    | SelectTable String
    | GotSchemaAndData String (Result Http.Error ( TableSchema, TableData ))
    | GridMsg (Grid.Msg Row)
    | SearchChanged String
    | ToggleSidebar


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
    , fetchTables
    )



-- UPDATE


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
                            fetchSchemaAndData name

                        Nothing ->
                            Cmd.none
                    )

                Err err ->
                    ( { model | error = Just (httpErrorToString err) }, Cmd.none )

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
                , fetchSchemaAndData name
                )

        GotSchemaAndData name result ->
            case result of
                Ok ( schema, tableData ) ->
                    let
                        rows =
                            parseRows tableData

                        columns =
                            buildGridColumns tableData.columns tableData.types name

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

                        gridModel =
                            Grid.init gridConfig rows
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
                    ( { model | error = Just (httpErrorToString err) }, Cmd.none )

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
                                -- Set filter on every column for OR-style search
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



-- VIEW


view : Model -> Html Msg
view model =
    div [ class "app" ]
        [ viewSidebar model
        , viewMain model
        ]


viewSidebar : Model -> Html Msg
viewSidebar model =
    nav
        [ id "sidebar"
        , class
            (if model.sidebarCollapsed then
                "collapsed"

             else
                ""
            )
        ]
        [ div [ id "sidebar-header" ]
            [ Html.h1 [] [ text "cass" ]
            , button
                [ class "collapse-btn"
                , onClick ToggleSidebar
                , title "Collapse sidebar"
                ]
                [ text "\u{2039}" ]
            ]
        , div [ id "table-list" ] (viewTableGroups model)
        ]


viewTableGroups : Model -> List (Html Msg)
viewTableGroups model =
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
                [ div [ class "section-group" ]
                    (div [ class "section-label" ] [ text label ]
                        :: List.map (viewTableItem model.selectedTable) items
                    )
                ]
    in
    viewGroup "Combined Data" master
        ++ viewGroup "Canvas LMS" canvas
        ++ viewGroup "GitHub Classroom" github


viewTableItem : Maybe String -> TableInfo -> Html Msg
viewTableItem selected t =
    div
        [ class
            (if selected == Just t.name then
                "table-item active"

             else
                "table-item"
            )
        , onClick (SelectTable t.name)
        ]
        [ span [] [ text t.name ] ]


viewMain : Model -> Html Msg
viewMain model =
    div [ id "main" ]
        [ if model.sidebarCollapsed then
            button
                [ id "sidebar-toggle"
                , onClick ToggleSidebar
                , title "Show sidebar"
                ]
                [ text "\u{203A}" ]

          else
            text ""
        , viewToolbar model
        , viewGridArea model
        ]


viewToolbar : Model -> Html Msg
viewToolbar model =
    div [ id "toolbar" ]
        [ span [ id "table-name" ]
            [ text (Maybe.withDefault "" model.selectedTable) ]
        , viewBadge model
        , span [ id "table-info" ] [ text (rowCountText model) ]
        , div [ class "toolbar-right" ]
            [ input
                [ id "search-box"
                , type_ "text"
                , placeholder "Search rows..."
                , value model.searchText
                , onInput SearchChanged
                , disabled (model.gridModel == Nothing)
                ]
                []
            ]
        ]


viewBadge : Model -> Html Msg
viewBadge model =
    case model.schema of
        Just schema ->
            if schema.editable then
                span [ id "table-badge", class "editable" ] [ text "EDITABLE" ]

            else
                span [ id "table-badge", class "readonly" ] [ text "READ-ONLY" ]

        Nothing ->
            text ""


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
        String.fromInt count ++ " rows \u{00B7} " ++ String.fromInt colCount ++ " columns"

    else
        ""


viewGridArea : Model -> Html Msg
viewGridArea model =
    case model.gridModel of
        Just gm ->
            div [ id "grid-container" ]
                [ Html.map GridMsg (Grid.view gm) ]

        Nothing ->
            case model.error of
                Just err ->
                    div [ id "empty-state" ]
                        [ div [ style "color" "var(--error)" ] [ text err ] ]

                Nothing ->
                    div [ id "empty-state" ]
                        [ div [] [ text "Select a table from the sidebar" ] ]



-- GRID COLUMN BUILDING


{-| Columns to hide for specific tables.
-}
hiddenColumns : Dict String (List String)
hiddenColumns =
    Dict.fromList
        [ ( "canvas_assignments", [ "canvas_id" ] )
        , ( "canvas_students", [ "canvas_id" ] )
        , ( "canvas_submissions", [ "canvas_user_id", "canvas_assignment_id" ] )
        , ( "canvas_grades", [ "canvas_user_id", "canvas_assignment_id" ] )
        ]


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

                        width =
                            estimateWidth colName colType
                    in
                    Just
                        (stringColumnConfig
                            { id = colName
                            , getter = \row -> Dict.get colName row.values |> Maybe.withDefault ""
                            , localize = identity
                            , title = colName
                            , tooltip = colType
                            , width = width
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



-- HTTP


fetchTables : Cmd Msg
fetchTables =
    Http.get
        { url = "/api/tables"
        , expect = Http.expectJson GotTables tablesDecoder
        }


{-| Fetch schema and data in parallel using Tasks, then combine.
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



-- HELPERS


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
