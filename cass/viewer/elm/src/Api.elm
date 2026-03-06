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
