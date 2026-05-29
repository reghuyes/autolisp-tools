(defun A1V2:GetDoc nil
  (vla-get-ActiveDocument (vlax-get-acad-object))
)

(defun A1V2:GetModelSpace (/ doc)
  (setq doc (A1V2:GetDoc))
  (vla-get-ModelSpace doc)
)

(defun A1V2:EnsureLayer (name color /)
  (if (tblsearch "LAYER" name)
    (command "_.layer" "_color" (itoa color) name "")
    (command "_.layer" "_new" name "_color" (itoa color) name "")
  )
  name
)

(defun A1V2:GetDrawingUnit (/ iu)
  (setq iu (getvar "INSUNITS"))
  (if (member iu '(1 2 4 5 6))
    iu
    (progn
      (initget "MM CM M IN FT")
      (setq iu (getkword "\nDrawing unit not detected. Select [MM/CM/M/IN/FT] <M>: "))
      (cond
        ((= iu "MM") 4)
        ((= iu "CM") 5)
        ((= iu "M")  6)
        ((= iu "IN") 1)
        ((= iu "FT") 2)
        (T 6)
      )
    )
  )
)

(defun A1V2:GetSqmPerDrawingUnit (insunits /)
  (cond
    ((= insunits 4) 0.000001)
    ((= insunits 5) 0.0001)
    ((= insunits 6) 1.0)
    ((= insunits 1) 0.00064516)
    ((= insunits 2) 0.09290227)
    (T 1.0)
  )
)

(defun A1V2:GetTargetFactorFromSqm (unitChoice /)
  (cond
    ((= unitChoice "Cent")     0.0247105)
    ((= unitChoice "Sq.m")     1.0)
    ((= unitChoice "Sq.ft")    10.764)
    ((= unitChoice "Sq.links") 24.7105)
    (T 1.0)
  )
)

(defun A1V2:GetAreaFactor (insunits unitChoice /)
  (* (A1V2:GetSqmPerDrawingUnit insunits)
     (A1V2:GetTargetFactorFromSqm unitChoice))
)

(defun A1V2:GetSuffix (unitChoice /)
  (cond
    ((= unitChoice "Cent") " Cents")
    ((= unitChoice "Sq.m") " Sq.m")
    ((= unitChoice "Sq.ft") " Sq.ft")
    ((= unitChoice "Sq.links") " Sq.links")
    (T "")
  )
)

(defun A1V2:GetInitialUnitDefault (insunits /)
  (cond
    ((= insunits 6) "C")
    ((= insunits 1) "F")
    (T "C")
  )
)

(defun A1V2:GetUnitBucket (insunits /)
  (if (= insunits 1) "Imperial" "Metric")
)

(defun A1V2:GetRememberedUnitDefault (insunits /)
  (if (= (A1V2:GetUnitBucket insunits) "Imperial")
    (progn
      (if (null *A1V2-UnitDefault-Imperial*)
        (setq *A1V2-UnitDefault-Imperial* (A1V2:GetInitialUnitDefault insunits))
      )
      *A1V2-UnitDefault-Imperial*
    )
    (progn
      (if (null *A1V2-UnitDefault-Metric*)
        (setq *A1V2-UnitDefault-Metric* (A1V2:GetInitialUnitDefault insunits))
      )
      *A1V2-UnitDefault-Metric*
    )
  )
)

(defun A1V2:SetRememberedUnitDefault (insunits val /)
  (if (= (A1V2:GetUnitBucket insunits) "Imperial")
    (setq *A1V2-UnitDefault-Imperial* val)
    (setq *A1V2-UnitDefault-Metric* val)
  )
  val
)

(defun A1V2:GetInitialHeightDefault (insunits /)
  (cond
    ((= insunits 6) 0.40)
    ((= insunits 1) 11.0)
    (T 0.40)
  )
)

(defun A1V2:GetRememberedHeightDefault (insunits /)
  (if (= (A1V2:GetUnitBucket insunits) "Imperial")
    (progn
      (if (null *A1V2-HeightDefault-Imperial*)
        (setq *A1V2-HeightDefault-Imperial* (A1V2:GetInitialHeightDefault insunits))
      )
      *A1V2-HeightDefault-Imperial*
    )
    (progn
      (if (null *A1V2-HeightDefault-Metric*)
        (setq *A1V2-HeightDefault-Metric* (A1V2:GetInitialHeightDefault insunits))
      )
      *A1V2-HeightDefault-Metric*
    )
  )
)

(defun A1V2:SetRememberedHeightDefault (insunits val /)
  (if (= (A1V2:GetUnitBucket insunits) "Imperial")
    (setq *A1V2-HeightDefault-Imperial* val)
    (setq *A1V2-HeightDefault-Metric* val)
  )
  val
)

(defun A1V2:ExpandUnitChoice (short /)
  (cond
    ((= short "C") "Cent")
    ((= short "S") "Sq.m")
    ((= short "F") "Sq.ft")
    ((= short "L") "Sq.links")
  )
)

(defun A1V2:GetPrefix nil
  (if (null *A1V2-Prefix*)
    (setq *A1V2-Prefix* "")
  )
  *A1V2-Prefix*
)

(defun A1V2:PromptAreaUnit (insunits / def ans)
  (setq def (A1V2:GetRememberedUnitDefault insunits))
  (initget "C S F L")
  (setq ans
    (getkword
      (strcat
        "\nSelect area unit [C=Cent/S=Sq.m/F=Sq.ft/L=Sq.links] <"
        def
        ">: "
      )
    )
  )
  (if (null ans)
    (setq ans def)
  )
  (A1V2:SetRememberedUnitDefault insunits ans)
  (A1V2:ExpandUnitChoice ans)
)

(defun A1V2:PromptHeight (insunits / def ans)
  (setq def (A1V2:GetRememberedHeightDefault insunits))
  (setq ans (getreal (strcat "\nEnter MText Height <" (rtos def 2 2) ">: ")))
  (if (null ans)
    (setq ans def)
  )
  (A1V2:SetRememberedHeightDefault insunits ans)
)

(defun A1V2:ValidAreaObjectP (ename / obj oname)
  (if ename
    (progn
      (setq obj   (vlax-ename->vla-object ename)
            oname (vla-get-ObjectName obj))
      (and
        (vlax-property-available-p obj 'Area)
        (or
          (and (= oname "AcDbPolyline")
               (= (vla-get-Closed obj) :vlax-true))
          (= oname "AcDbHatch")
          (= oname "AcDbRegion")
          (= oname "AcDbCircle")
          (= oname "AcDbEllipse")
        )
      )
    )
  )
)

(defun A1V2:DrawPlineAndGet (/ lastent newent obj)
  (setq lastent (entlast))
  (command "_.PLINE")
  (while (> (getvar "CMDACTIVE") 0)
    (command pause)
  )
  (setq newent (entlast))
  (if (and newent (/= newent lastent))
    (progn
      (setq obj (vlax-ename->vla-object newent))
      (if (and (= (vla-get-ObjectName obj) "AcDbPolyline")
               (= (vla-get-Closed obj) :vlax-true))
        newent
        (progn
          (princ "\nPolyline was not closed.")
          nil
        )
      )
    )
  )
)

(defun A1V2:GetAreaObject (/ sel)
  (while
    (progn
      (initget "Draw")
      (setq sel (entsel "\nSelect closed polyline / hatch / region / circle / ellipse [Draw]: "))
      (cond
        ((= sel "Draw")
         (setq sel (A1V2:DrawPlineAndGet))
         nil
        )
        ((null sel)
         (princ "\nNothing selected.")
         nil
        )
        ((A1V2:ValidAreaObjectP (car sel))
         (setq sel (car sel))
         nil
        )
        (T
         (princ "\nInvalid selection. Object must support Area, and polylines must be closed.")
         T
        )
      )
    )
  )
  sel
)

(defun A1V2:BuildAreaField (ename prefix suffix factor unitChoice / objid prec)
  (setq objid (itoa (vla-get-ObjectID (vlax-ename->vla-object ename))))
  (setq prec
    (if (= unitChoice "Cent")
      "3"
      "2"
    )
  )
  (strcat
    prefix
    "%<\\AcObjProp Object(%<\\_ObjId "
    objid
    " >%).Area \\f \"%lu2%pr"
    prec
    "%ct8["
    (rtos factor 2 12)
    "]\">%"
    suffix
  )
)

(defun A1V2:CreateMText (pt txt hgt layer / ms mt)
  (setq ms (A1V2:GetModelSpace))
  (setq mt (vla-AddMText ms (vlax-3d-point pt) 0 txt))
  (vla-put-Height mt hgt)
  (vla-put-Layer mt layer)
  (vla-put-AttachmentPoint mt acAttachmentPointMiddleCenter)
  mt
)

(defun A1V2:InitSettings (/)
  (if (null *A1V2-LayerName*)              (setq *A1V2-LayerName* "A_Annotations"))
  (if (null *A1V2-LayerColor*)             (setq *A1V2-LayerColor* 223))
  (if (null *A1V2-Prefix*)                 (setq *A1V2-Prefix* ""))
  (if (null *A1V2-HeightDefault-Metric*)   (setq *A1V2-HeightDefault-Metric* 0.40))
  (if (null *A1V2-HeightDefault-Imperial*) (setq *A1V2-HeightDefault-Imperial* 11.0))
)

(defun c:A1SET (/ ans)
  (A1V2:InitSettings)

  (princ (strcat "\nCurrent layer name         : " *A1V2-LayerName*))
  (princ (strcat "\nCurrent layer color        : " (itoa *A1V2-LayerColor*)))
  (princ (strcat "\nCurrent prefix             : " *A1V2-Prefix*))
  (princ (strcat "\nText height for meter      : " (rtos *A1V2-HeightDefault-Metric* 2 2)))
  (princ (strcat "\nText height for inches     : " (rtos *A1V2-HeightDefault-Imperial* 2 2)))

  (setq ans (getstring T (strcat "\nEnter layer name <" *A1V2-LayerName* ">: ")))
  (if (/= ans "") (setq *A1V2-LayerName* ans))

  (setq ans (getint (strcat "\nEnter layer color <" (itoa *A1V2-LayerColor*) ">: ")))
  (if ans (setq *A1V2-LayerColor* ans))

  (setq ans (getstring T (strcat "\nEnter prefix text <" *A1V2-Prefix* ">: ")))
  (if (/= ans "") (setq *A1V2-Prefix* ans))

  (setq ans (getreal (strcat "\nEnter text height for meter <" (rtos *A1V2-HeightDefault-Metric* 2 2) ">: ")))
  (if ans (setq *A1V2-HeightDefault-Metric* ans))

  (setq ans (getreal (strcat "\nEnter text height for inches <" (rtos *A1V2-HeightDefault-Imperial* 2 2) ">: ")))
  (if ans (setq *A1V2-HeightDefault-Imperial* ans))

  (princ "\nA1 settings updated.")
  (princ)
)

(defun c:A1RESET nil
  (setq *A1V2-UnitDefault-Metric* nil)
  (setq *A1V2-UnitDefault-Imperial* nil)
  (setq *A1V2-HeightDefault-Metric* nil)
  (setq *A1V2-HeightDefault-Imperial* nil)
  (setq *A1V2-Prefix* nil)
  (setq *A1V2-LayerName* nil)
  (setq *A1V2-LayerColor* nil)
  (princ "\nA1 defaults reset.")
  (princ)
)

(defun c:A1 (/ *error* oldCmdecho doc ename insunits mtht unitChoice factor suffix inspt areaField mtobj)

  (defun *error* (msg)
    (if oldCmdecho (setvar "CMDECHO" oldCmdecho))
    (if (and msg
             (/= msg "Function cancelled")
             (/= msg "quit / exit abort"))
      (princ (strcat "\nError: " msg))
    )
    (princ)
  )

  (A1V2:InitSettings)

  (setq oldCmdecho (getvar "CMDECHO"))
  (setvar "CMDECHO" 0)

  (setq insunits (A1V2:GetDrawingUnit))

  (A1V2:EnsureLayer *A1V2-LayerName* *A1V2-LayerColor*)

  (setq ename (A1V2:GetAreaObject))
  (if (null ename)
    (progn
      (setvar "CMDECHO" oldCmdecho)
      (princ)
      (exit)
    )
  )

  (setq mtht       (A1V2:PromptHeight insunits))
  (setq unitChoice (A1V2:PromptAreaUnit insunits))
  (setq factor     (A1V2:GetAreaFactor insunits unitChoice))
  (setq suffix     (A1V2:GetSuffix unitChoice))
  (setq inspt      (getpoint "\nMText Insertion Point: "))

  (if (null inspt)
    (progn
      (setvar "CMDECHO" oldCmdecho)
      (princ "\nPoint not selected.")
      (princ)
      (exit)
    )
  )

  (setq areaField (A1V2:BuildAreaField ename (A1V2:GetPrefix) suffix factor unitChoice))
  (setq mtobj (A1V2:CreateMText inspt areaField mtht *A1V2-LayerName*))

  (setq doc (A1V2:GetDoc))
  (vla-Regen doc acAllViewports)

  (setvar "CMDECHO" oldCmdecho)
  (princ)
)