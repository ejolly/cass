module Types exposing
    ( CanvasChange
    , ColumnSchema
    , EditState
    , Model
    , Msg(..)
    , PreviewData
    , PushResult
    , Row
    , StatusMessage
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


{-| A transient status message shown in the toolbar (e.g. "Saved", "Push failed").
-}
type alias StatusMessage =
    { text : String
    , statusClass : String
    }


{-| State for the inline cell editor overlay.
-}
type alias EditState =
    { column : String
    , value : String
    , originalValue : String
    , pk : Dict String String
    }


{-| A single change in the Canvas preview diff.
-}
type alias CanvasChange =
    { table : String
    , name : String
    , column : String
    , live : Maybe String
    , current : Maybe String
    , conflict : Bool
    , error : Maybe String
    }


{-| Preview data returned from /api/canvas/preview.
-}
type alias PreviewData =
    { changes : List CanvasChange
    , hasConflicts : Bool
    , hasErrors : Bool
    }


{-| Result of a single push operation from /api/canvas/apply.
-}
type alias PushResult =
    { ok : Bool
    , canvasId : Maybe Int
    , error : Maybe String
    }


type alias Model =
    { tables : List TableInfo
    , selectedTable : Maybe String
    , schema : Maybe TableSchema
    , rows : List Row
    , gridModel : Maybe (Grid.Model Row)
    , searchText : String
    , sidebarCollapsed : Bool
    , error : Maybe String
    , pendingCount : Int
    , statusMessage : Maybe StatusMessage
    , columnNames : List String
    , columnTypes : List String
    , filteredRowCount : Int
    , editing : Maybe EditState
    , showModal : Bool
    , modalLoading : Bool
    , modalPushing : Bool
    , previewData : Maybe PreviewData
    , pushResults : Maybe (List PushResult)
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
    | GotPending (Result Http.Error Int)
    | ClearStatus String
    | ExportCsv
    | FocusSearch
    | EscapePressed
    | NoOp
      -- Cell editing
    | CellClickedRaw D.Value
    | StartEdit String String (Dict String String)
    | EditChanged String
    | CommitEdit
    | CancelEdit
    | GotUpdateResult String (Dict String String) String (Result Http.Error { ok : Bool, error : Maybe String, pendingCount : Maybe Int })
      -- Canvas push modal
    | OpenPushModal
    | ClosePushModal
    | GotPreview (Result Http.Error PreviewData)
    | ApplyPush
    | GotApplyResult (Result Http.Error { ok : Bool, results : List PushResult })
