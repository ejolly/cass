module Api exposing
    ( applyPush
    , buildCsvContent
    , fetchPending
    , fetchPreview
    , fetchSchemaAndData
    , fetchTables
    , httpErrorToString
    , matchesSearch
    , parseRows
    , updateCell
    )

{-| HTTP requests and JSON decoders for the viewer API.

In Svelte you'd use `fetch` in a `+page.ts` loader or an `onMount`.
In Elm, HTTP is a side effect — you return a `Cmd` from `update` and
the runtime executes it, calling you back with the result as a `Msg`.
No `async/await`, no `try/catch` — just data in, data out.

-}

import Dict exposing (Dict)
import Http
import Json.Decode as D
import Json.Encode as E
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


{-| Fetch the pending Canvas changes count.
-}
fetchPending : Cmd Msg
fetchPending =
    Http.get
        { url = "/api/pending"
        , expect = Http.expectJson GotPending (D.field "count" D.int)
        }


{-| POST a cell update to the server.
-}
updateCell : String -> Dict String String -> String -> String -> Cmd Msg
updateCell table pk column value =
    let
        pkJson =
            E.object (List.map (\( k, v ) -> ( k, E.string v )) (Dict.toList pk))

        body =
            E.object
                [ ( "pk", pkJson )
                , ( "column", E.string column )
                , ( "value", E.string value )
                ]
    in
    Http.post
        { url = "/api/update/" ++ table
        , body = Http.jsonBody body
        , expect =
            Http.expectJson (GotUpdateResult table)
                (D.map3
                    (\ok err pc -> { ok = ok, error = err, pendingCount = pc })
                    (D.field "ok" D.bool)
                    (D.maybe (D.field "error" D.string))
                    (D.maybe (D.field "pending_count" D.int))
                )
        }


{-| POST to fetch Canvas preview data.
-}
fetchPreview : Cmd Msg
fetchPreview =
    Http.post
        { url = "/api/canvas/preview"
        , body = Http.emptyBody
        , expect = Http.expectJson GotPreview previewDecoder
        }


{-| POST to apply pending changes to Canvas.
-}
applyPush : Cmd Msg
applyPush =
    Http.post
        { url = "/api/canvas/apply"
        , body = Http.emptyBody
        , expect =
            Http.expectJson GotApplyResult
                (D.map2
                    (\ok results -> { ok = ok, results = results })
                    (D.field "ok" D.bool)
                    (D.field "results"
                        (D.list
                            (D.map3
                                (\ok cid err -> PushResult ok cid err)
                                (D.field "ok" D.bool)
                                (D.maybe (D.field "canvas_id" D.int))
                                (D.maybe (D.field "error" D.string))
                            )
                        )
                    )
                )
        }


previewDecoder : D.Decoder PreviewData
previewDecoder =
    D.map3 PreviewData
        (D.field "changes"
            (D.list
                (D.map7 CanvasChange
                    (D.field "table" D.string)
                    (D.oneOf [ D.field "name" D.string, D.succeed "" ])
                    (D.oneOf [ D.field "column" D.string, D.succeed "" ])
                    (D.maybe (D.field "live" jsonToMaybeString))
                    (D.maybe (D.field "current" jsonToMaybeString))
                    (D.oneOf [ D.field "conflict" D.bool, D.succeed False ])
                    (D.maybe (D.field "error" D.string))
                )
            )
        )
        (D.oneOf [ D.field "has_conflicts" D.bool, D.succeed False ])
        (D.oneOf [ D.field "has_errors" D.bool, D.succeed False ])


{-| Decode a JSON value to Maybe String, handling null/numbers/booleans.
-}
jsonToMaybeString : D.Decoder String
jsonToMaybeString =
    D.oneOf
        [ D.string
        , D.float |> D.map String.fromFloat
        , D.int |> D.map String.fromInt
        , D.bool
            |> D.map
                (\b ->
                    if b then
                        "Yes"

                    else
                        "No"
                )
        ]


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



-- SEARCH


{-| True if any column value in the row contains the query (case-insensitive).

This is the OR-across-columns "quick filter" equivalent of AG Grid's
`quickFilterText`. The grid library's built-in `SetFilters` uses AND
logic, which is wrong for a global search box.

-}
matchesSearch : String -> Row -> Bool
matchesSearch query row =
    let
        lowerQuery =
            String.toLower query
    in
    Dict.values row.values
        |> List.any (\val -> String.contains lowerQuery (String.toLower val))



-- CSV EXPORT


{-| Build a CSV string from column names and rows.

Handles quoting for values that contain commas, quotes, or newlines.

-}
buildCsvContent : List String -> List Row -> String
buildCsvContent columns rows =
    let
        escapeCsvField val =
            if String.contains "," val || String.contains "\"" val || String.contains "\n" val then
                "\"" ++ String.replace "\"" "\"\"" val ++ "\""

            else
                val

        header =
            String.join "," columns

        rowLine row =
            columns
                |> List.map (\col -> Dict.get col row.values |> Maybe.withDefault "" |> escapeCsvField)
                |> String.join ","
    in
    (header :: List.map rowLine rows)
        |> String.join "\n"


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
